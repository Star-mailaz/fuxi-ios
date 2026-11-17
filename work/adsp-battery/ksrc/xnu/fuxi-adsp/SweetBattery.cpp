/*
 * Built-in iOS battery bring-up service. Default: 100%, AC, not charging.
 * sweetbattery=1: read-only PM6150 polling every 30 seconds; voltage-derived
 * SOC is an UNCALIBRATED estimate, not a replacement for the Linux QG algo.
 * See report.md for binary evidence, register provenance and integration.
 */
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <device/device_types.h> /* io_buf_ptr_t for private OSKext headers */
#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#if defined(FUXI)
#include <IOKit/IOInterruptEventSource.h>
#endif
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <IOKit/pwr_mgt/IOPM.h>
#include <libkern/c++/OSCollectionIterator.h>
#include <pexpert/pexpert.h>
/* bsd/dev/sweet_spmi.c */
extern "C" int sweet_spmi_init(void);
extern "C" int sweet_spmi_read(unsigned sid, unsigned addr, uint8_t *out);
/* bsd/kern/proc.c */
extern "C" void proc_selfname(char *buf, int size);
#if defined(FUXI)
#include "../../../bsd/dev/fuxi_adsp_battery.h"
#include "../../../bsd/dev/fuxi_battery_freshness.h"
#endif

class SweetBattery : public IOPMPowerSource {
	OSDeclareDefaultStructors(SweetBattery);
public:
	bool init(OSDictionary *dictionary = NULL) APPLE_KEXT_OVERRIDE;
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	void stop(IOService *provider) APPLE_KEXT_OVERRIDE;
	void free(void) APPLE_KEXT_OVERRIDE;
	bool serializeProperties(OSSerialize *s) const APPLE_KEXT_OVERRIDE;
private:
	IOWorkLoop *fLoop;
	IOTimerEventSource *fTimer;
	bool fTimerAdded, fRunning, fReal, fAdsp, fAdspShown;
	int fLastMode;
	unsigned fShown, fShownLogs;
	void putNumber(const char *key, UInt32 value);
	void putBool(const char *key, bool value);
	void publish(unsigned percent, unsigned mv, int ma, bool external,
	    bool capable, bool charging, bool full, bool measured, bool currentValid);
	void poll(void);
#if defined(FUXI)
	void publishAdsp(const FuxiAdspBattery &b);
	FuxiAdspBattery fAdspLast;
	bool fAdspSOCShown, fAdspTemperatureShown;
	IOInterruptEventSource *fNotify;
	bool fNotifyAdded;
#endif
	static void timerFired(OSObject *owner, IOTimerEventSource *sender);
#if defined(FUXI)
	static void adspChanged(void *owner);
	static void adspChangedFired(OSObject *owner, IOInterruptEventSource *sender, int count);
#endif
	static IOReturn stopPolling(OSObject *owner, void *, void *, void *, void *);
	static bool readWord(unsigned address, uint16_t *value);
	static unsigned estimatePercent(unsigned mv);
};
OSDefineMetaClassAndStructors(SweetBattery, IOPMPowerSource);

/* Who reads the battery from user space (IORegistryEntryCreateCFProperties) and what it then
 * sees, bounded: the first 16 reads, then the first 4 after each change of what is published. */
static uint32_t gSbReads, gSbReadLogs, gSbReadKey = ~0u, gSbReadsSinceChange;

bool
SweetBattery::serializeProperties(OSSerialize *s) const
{
	const uint32_t n = __atomic_add_fetch(&gSbReads, 1u, __ATOMIC_RELAXED);
	const unsigned key = fShown;
	if (key != gSbReadKey) {
		gSbReadKey = key;
		gSbReadsSinceChange = 0;
	}
	if ((n <= 16 || gSbReadsSinceChange++ < 4) && gSbReadLogs < 96) {
		char name[32];
		gSbReadLogs++;
		proc_selfname(name, (int)sizeof(name));
		if (key == ~0u)
			IOLog("SWEET BATTERY: read #%u by %s (still the fallback)\n", n, name);
		else
			IOLog("SWEET BATTERY: read #%u by %s (published #%u: %u%% external=%u charging=%u)\n", n, name,
			    fShownLogs, key & 0xffu, (key >> 8) & 0xfu ? ((key >> 8) & 0xfu) - 1u : 9u,
			    (key >> 12) & 0xfu ? ((key >> 12) & 0xfu) - 1u : 9u);
	}
	return IOPMPowerSource::serializeProperties(s);
}

bool
SweetBattery::init(OSDictionary *dictionary)
{
	/* IOCatalogue calls init(dictionary). This XNU's IOPMPowerSource only
	 * overrides init(void): explicitly run it to allocate its PS dictionary
	 * and symbols, then copy the matching personality into the registry. */
	if (!IOPMPowerSource::init()) {
		return false;
	}
	fLoop = NULL;
	fTimer = NULL;
	fTimerAdded = fRunning = fReal = fAdsp = fAdspShown = false;
#if defined(FUXI)
	fNotify = NULL;
	fNotifyAdded = false;
	bzero(&fAdspLast, sizeof(fAdspLast));
	fAdspSOCShown = fAdspTemperatureShown = false;
	fAdspLast.percent = 100;
	fAdspLast.voltage_mv = 4200;
	fAdspLast.temperature = 2500;
	fAdspLast.full_mah = fAdspLast.design_mah = 5020;
	fAdspLast.present = fAdspLast.external = fAdspLast.fully_charged = 1;
	fAdspLast.minutes_to_empty = fAdspLast.minutes_to_full = -1;
#endif
	if (dictionary) {
		OSCollectionIterator *it = OSCollectionIterator::withCollection(dictionary);
		if (!it) {
			return false;
		}
		OSObject *object;
		bool ok = true;
		while ((object = it->getNextObject())) {
			const OSSymbol *key = OSDynamicCast(OSSymbol, object);
			if (!key || !setProperty(key, dictionary->getObject(key))) {
				ok = false;
				break;
			}
		}
		it->release();
		if (!ok) {
			return false;
		}
	}
	fLastMode = -1;
	fShown = ~0u;
	fShownLogs = 0;
	return true;
}

void
SweetBattery::putNumber(const char *key, UInt32 value)
{
	const OSSymbol *symbol = OSSymbol::withCString(key);
	OSNumber *number = OSNumber::withNumber(value, 32);
	if (symbol && number) {
		setPSProperty(symbol, number);
	}
	OSSafeReleaseNULL(number);
	OSSafeReleaseNULL(symbol);
}

void
SweetBattery::putBool(const char *key, bool value)
{
	const OSSymbol *symbol = OSSymbol::withCString(key);
	if (symbol) {
		setPSProperty(symbol, value ? kOSBooleanTrue : kOSBooleanFalse);
		symbol->release();
	}
}

void
SweetBattery::publish(unsigned percent, unsigned mv, int ma, bool external,
    bool capable, bool charging, bool full, bool measured, bool currentValid)
{
	/* Use consistent mAh units (DT nominal=5020). powerd computes C*100/M. */
	const unsigned capacity = (5020u * percent + 50u) / 100u;
	setBatteryInstalled(true);
	setCurrentCapacity(capacity);
	setMaxCapacity(5020);
	setExternalConnected(external);
	setExternalChargeCapable(capable);
	setIsCharging(charging);
	setAtWarnLevel(false);
	/* An uncalibrated voltage curve must not assert a critical shutdown. */
	setAtCriticalLevel(false);
	setVoltage(mv);
	setAmperage(ma);
	setTimeRemaining(-1); /* Unknown; never publish zero minutes on error. */
	setCycleCount(0);     /* Placeholder: cycle learning is not implemented. */
	putBool("FullyCharged", full);
	putBool("AppleRawExternalConnected", external);
	putNumber("AppleRawCurrentCapacity", capacity);
	putNumber("AppleRawMaxCapacity", 5020);
	putNumber("DesignCapacity", 5020);
	putNumber("InstantAmperage", (UInt32)ma);
	/* iOS battery convention: centidegrees C; fixed 25 C, NOT measured. */
	putNumber("Temperature", 2500);
	putBool("SweetBatteryHardwareSampleValid", measured);
	putBool("SweetBatteryCurrentValid", currentValid);
	putBool("SweetBatterySOCEstimated", measured);
	putBool("SweetBatteryTemperatureEstimated", true);
	putBool("SweetBatteryFallback", !measured);
	putNumber("SweetBatteryPercent", percent);

	/* IOPMCopyBatteryInfo's per-source compatibility dictionary. */
	OSDictionary *legacy = OSDictionary::withCapacity(7);
	if (legacy) {
		const char *keys[] = {kIOBatteryCurrentChargeKey, kIOBatteryCapacityKey,
		    kIOBatteryVoltageKey, kIOBatteryAmperageKey, kIOBatteryCycleCountKey,
		    kIOBatteryFlagsKey};
		UInt32 values[] = {capacity, 5020, mv, (UInt32)ma, 0,
		    (UInt32)(kIOBatteryInstalled | (external ? kIOBatteryChargerConnect : 0) |
		    (charging ? kIOBatteryCharge : 0))};
		for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
			OSNumber *number = OSNumber::withNumber(values[i], 32);
			if (number) {
				legacy->setObject(keys[i], number);
				number->release();
			}
		}
		setLegacyIOBatteryInfo(legacy);
		legacy->release();
	}
	updateStatus(); /* Flush PS properties and send 0xe0024100 on change. */
	int mode = measured ? 1 : 0;
	if (mode != fLastMode) {
		IOLog("SWEET BATTERY: %s, %u%% %umV external=%d charging=%d\n",
		    measured ? "PM6150 / estimated SOC" : "static fallback",
		    percent, mv, external, charging);
		fLastMode = mode;
	}
}

/* Keep the proven single-byte observer command. Read two matching whole
 * words to reject most torn ADC samples without writing the QG HOLD bit.
 * This is a bounded consistency check, not a hardware snapshot guarantee. */
bool
SweetBattery::readWord(unsigned address, uint16_t *value)
{
	uint16_t previous = 0;
	for (unsigned attempt = 0; attempt < 4; ++attempt) {
		uint8_t lo, hi;
		if (sweet_spmi_read(0, address, &lo) ||
		    sweet_spmi_read(0, address + 1, &hi)) {
			return false;
		}
		uint16_t next = (uint16_t)((unsigned)lo | ((unsigned)hi << 8));
		if (attempt && next == previous) {
			*value = next;
			return true;
		}
		previous = next;
	}
	return false;
}

unsigned
SweetBattery::estimatePercent(unsigned mv)
{
	/* Generic single-cell curve, intentionally NOT advertised as QG SOC.
	 * Load sag, temperature, aging and charging introduce large errors. */
	static const unsigned volts[] = {3400, 3500, 3600, 3700, 3800, 3900,
	    4000, 4100, 4200, 4350};
	static const unsigned soc[] = {1, 5, 10, 20, 40, 60, 75, 85, 93, 100};
	if (mv <= volts[0]) {
		return soc[0];
	}
	for (unsigned i = 1; i < sizeof(volts) / sizeof(volts[0]); ++i) {
		if (mv < volts[i]) {
			return soc[i - 1] + (mv - volts[i - 1]) * (soc[i] - soc[i - 1]) /
			       (volts[i] - volts[i - 1]);
		}
	}
	return 100;
}

#if defined(FUXI)
void
SweetBattery::publishAdsp(const FuxiAdspBattery &incoming)
{
	fuxi_battery_prep_merge(&fAdspLast, &incoming);
	const FuxiAdspBattery &b = fAdspLast;
	fAdspSOCShown = fAdspSOCShown || b.soc_known;
	fAdspTemperatureShown = fAdspTemperatureShown || b.temperature_valid;
	/* mAh as publish() uses them (powerd computes C*100/M); Xiaomi 13: 4500 mAh. */
	const unsigned design = b.design_mah > 0 ? (unsigned)b.design_mah : 4500u;
	const unsigned full = b.full_mah > 0 ? (unsigned)b.full_mah : design;
	const unsigned capacity = (full * (unsigned)b.percent + 50u) / 100u;
	setBatteryInstalled(b.present != 0);
	setCurrentCapacity(capacity);
	setMaxCapacity(full);
	setExternalConnected(b.external != 0);
	setExternalChargeCapable(b.external != 0);
	putBool("AppleRawExternalConnected", b.external != 0);
	setIsCharging(b.charging != 0);
	putBool("FullyCharged", b.fully_charged != 0);
	{
		OSDictionary *adapter = OSDictionary::withCapacity(4);
		if (adapter) {
			const char *keys[] = {kIOPMPSAdapterDetailsFamilyKey, kIOPMPSAdapterDetailsVoltage,
			    kIOPMPSAdapterDetailsAmperageKey, kIOPMPSAdapterDetailsWattsKey};
			const UInt32 values[] = {b.external ? b.adapter_family : 0,
			    b.external && b.adapter_mv > 0 ? (UInt32)b.adapter_mv : 0,
			    b.external && b.adapter_ma > 0 ? (UInt32)b.adapter_ma : 0,
			    b.external && b.adapter_watts > 0 ? (UInt32)b.adapter_watts : 0};
			for (unsigned index = 0; index < sizeof(values) / sizeof(values[0]); index++) {
				OSNumber *number = OSNumber::withNumber(values[index], 32);
				if (number) {
					adapter->setObject(keys[index], number);
					number->release();
				}
			}
			const OSSymbol *key = OSSymbol::withCString(kIOPMPSAdapterDetailsKey);
			if (key) setPSProperty(key, adapter);
			OSSafeReleaseNULL(key);
			adapter->release();
		}
	}
	setAtWarnLevel(false);
	/* Never a critical shutdown from this path: the PMIC cuts off an empty cell. */
	setAtCriticalLevel(false);
	setVoltage(b.voltage_mv > 0 ? (unsigned)b.voltage_mv : 0);
	setAmperage(b.current_ma);
	const int minutes = b.charging ? b.minutes_to_full : b.minutes_to_empty;
	const uint32_t time_field = 1u << (b.charging ? BmTimeToFull : BmTimeToEmpty);
	setTimeRemaining(b.status_known && (b.fresh_fields & time_field) && minutes >= 0 ? minutes : -1);
	setCycleCount(b.cycles > 0 ? (unsigned)b.cycles : 0);
	putNumber("AppleRawCurrentCapacity", b.raw_mah > 0 ? (UInt32)b.raw_mah : capacity);
	putNumber("AppleRawMaxCapacity", full);
	putNumber("NominalChargeCapacity", full);
	putNumber("DesignCapacity", design);
	putNumber("InstantAmperage", (UInt32)b.current_ma);
	putNumber("Temperature", (UInt32)b.temperature);
	putBool("SweetBatteryHardwareSampleValid", b.soc_known && b.voltage_valid);
	putBool("SweetBatteryCurrentValid", b.current_valid != 0);
	putBool("SweetBatterySOCEstimated", !fAdspSOCShown);
	putBool("SweetBatteryTemperatureEstimated", !fAdspTemperatureShown);
	fAdspShown = fAdspShown || b.sequence != 0;
	putBool("SweetBatteryFallback", !fAdspShown);
	putBool("FuxiAdspBattery", true);
	putBool("FuxiBatterySourceStale", b.stale != 0);
	putBool("FuxiBatterySOCValid", b.soc_known != 0);
	putBool("FuxiBatteryVoltageValid", b.voltage_valid != 0);
	putBool("FuxiBatteryPresentValid", (b.fresh_fields & (1u << BmPresent)) != 0);
	putBool("FuxiBatteryRawCapacityValid", (b.fresh_fields & (1u << BmGauge1Remaining)) != 0);
	putBool("FuxiBatteryExternalKnown", b.external_known != 0);
	putBool("FuxiBatteryStatusKnown", b.status_known != 0);
	putBool("FuxiBatteryChannelUp", b.channel_up != 0);
	const uint32_t adapter_fields = (1u << BmUsbAdapter) | (1u << BmUsbVoltage) | (1u << BmUsbCurrent);
	putBool("FuxiBatteryAdapterValid", b.external_known &&
	    (!b.external || (b.fresh_fields & adapter_fields) == adapter_fields));
	putNumber("FuxiBatteryFreshFields", b.fresh_fields);
	putNumber("FuxiBatteryMaxAgeMs", b.max_age_ms);
	putNumber("FuxiBatterySOCAgeMs", b.soc_age_ms);
	putNumber("FuxiBatteryExternalAgeMs", b.external_age_ms);
	putNumber("FuxiBatteryStatusAgeMs", b.status_age_ms);
	putNumber("SweetBatteryPercent", (UInt32)b.percent);
	OSDictionary *legacy = OSDictionary::withCapacity(7);
	if (legacy) {
		const char *keys[] = {kIOBatteryCurrentChargeKey, kIOBatteryCapacityKey,
		    kIOBatteryVoltageKey, kIOBatteryAmperageKey, kIOBatteryCycleCountKey,
		    kIOBatteryFlagsKey};
		UInt32 values[] = {capacity, full, (UInt32)(b.voltage_mv > 0 ? b.voltage_mv : 0), (UInt32)b.current_ma,
		    (UInt32)(b.cycles > 0 ? b.cycles : 0),
		    (UInt32)((b.present ? kIOBatteryInstalled : 0) | (b.external ? kIOBatteryChargerConnect : 0) |
		    (b.charging ? kIOBatteryCharge : 0))};
		for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
			OSNumber *number = OSNumber::withNumber(values[i], 32);
			if (number) {
				legacy->setObject(keys[i], number);
				number->release();
			}
		}
		setLegacyIOBatteryInfo(legacy);
		legacy->release();
	}
	updateStatus();
	if (fLastMode != 2) {
		IOLog("SWEET BATTERY: ADSP battery manager, %d%% %dmV %dmA external=%d charging=%d\n",
		    b.percent, b.voltage_mv, b.current_ma, b.external, b.charging);
		fLastMode = 2;
	}
	/* What iOS is shown, each time it changes (bounded): percent, charger, charging, full. */
	const unsigned shown = ((unsigned)b.percent & 0xffu) | ((b.external_known ? 1u + b.external : 0u) << 8) |
	    ((b.status_known ? 1u + b.charging : 0u) << 12) | ((unsigned)b.fully_charged << 16) |
	    ((unsigned)b.stale << 17);
	if (shown != fShown) {
		fShown = shown;
		if (fShownLogs++ < 48)
			IOLog("SWEET BATTERY: published #%u %d%% external=%d%s charging=%d%s full=%d %dmA\n", fShownLogs, b.percent,
			    b.external, b.external_known ? "" : "(unknown)", b.charging, b.status_known ? "" : "(unknown)",
			    b.fully_charged, b.current_ma);
	}
}
#endif

void
SweetBattery::poll(void)
{
#if defined(FUXI)
	FuxiAdspBattery adsp;
	if (fAdsp || fAdspShown) {
		bzero(&adsp, sizeof(adsp));
		adsp.stale = 1;
		adsp.max_age_ms = FUXI_BATTERY_DEFAULT_MAX_AGE_MS;
		adsp.soc_age_ms = adsp.external_age_ms = adsp.status_age_ms = ~0u;
		(void)fuxi_adsp_battery_reading(&adsp);
		if (fLastMode == -1) publish(100, 4200, 0, true, true, false, true, false, false);
		publishAdsp(adsp);
		return;
	}
#endif
	uint8_t type, present, usb, path, charger, error, temperature;
	uint16_t rawVoltage;
	bool valid = fReal &&
	    !sweet_spmi_read(0, 0x4804, &type) && type == 0x0d &&
	    !sweet_spmi_read(0, 0x4808, &present) && (present & 1u) &&
	    readWord(0x48c0, &rawVoltage) && rawVoltage != 0x8000 &&
	    !sweet_spmi_read(0, 0x1310, &usb) &&
	    !sweet_spmi_read(0, 0x110b, &path) &&
	    !sweet_spmi_read(0, 0x1006, &charger) &&
	    !sweet_spmi_read(0, 0x1007, &error) &&
	    !sweet_spmi_read(0, 0x100d, &temperature);
	unsigned mv = valid ? (unsigned)(((uint64_t)rawVoltage * 194637u) / 1000000u) : 0;
	/* Zero, reset, floating, or implausible data cannot become 0% battery. */
	valid = valid && mv >= 2800 && mv <= 4600;
	if (!valid) {
		publish(100, 4200, 0, true, true, false, true, false, false);
		return;
	}
	bool external = (usb & 0x10u) != 0;
	bool capable = external && (path & 0x10u) && (path & 1u) && !(path & 0x40u);
	unsigned state = charger & 7u;
	bool charging = capable && state >= 1 && state <= 4 &&
	    !(error & 2u) && !(temperature & 0x0cu);
	/* Inhibit (0) does not by itself establish full capacity. */
	bool full = external && state == 5 && !(error & 2u);
	int ma = 0;
	uint8_t subtype;
	uint16_t rawCurrent;
	bool currentValid = !sweet_spmi_read(0, 0x4805, &subtype) &&
	    (subtype == 3 || subtype == 4) && readWord(0x48c2, &rawCurrent) &&
	    rawCurrent != 0x8000;
	if (currentValid) {
		int signedRaw = (rawCurrent & 0x8000u) ? (int)rawCurrent - 65536 : (int)rawCurrent;
		/* Linux: negative=charging; IOPMPowerSource: positive=charging, mA. */
		ma = (int)(-((int64_t)signedRaw * (subtype == 3 ? 152588 : 305176)) / 1000000);
	}
	publish(full ? 100 : estimatePercent(mv), mv, ma, external, capable,
	    charging, full, true, currentValid);
}

#if defined(FUXI)
void
SweetBattery::adspChanged(void *owner)
{
	SweetBattery *self = (SweetBattery *)owner;
	if (self && self->fNotify) {
		self->fNotify->interruptOccurred(NULL, NULL, 0);
	}
}

void
SweetBattery::adspChangedFired(OSObject *owner, IOInterruptEventSource *sender, int count)
{
	(void)sender;
	(void)count;
	SweetBattery *self = OSDynamicCast(SweetBattery, owner);
	if (self && self->fRunning) {
		self->poll();
	}
}
#endif

void
SweetBattery::timerFired(OSObject *owner, IOTimerEventSource *sender)
{
	SweetBattery *self = OSDynamicCast(SweetBattery, owner);
	if (self && self->fRunning) {
		self->poll();
		/* Every 10 s until the DSP's first reading arrives, then every 30 s. */
		sender->setTimeoutMS(self->fAdsp && !self->fAdspShown ? 10000 : 30000);
	}
}

bool
SweetBattery::start(IOService *provider)
{
	if (!IOPMPowerSource::start(provider)) {
		return false;
	}
	int real = 0;
	(void)PE_parse_boot_argn("sweetbattery", &real, sizeof(real));
	fReal = real == 1 && sweet_spmi_init() == 0;
#if defined(FUXI)
	fAdsp = fuxi_adsp_battery_wanted() != 0;
#endif
	/* Publish a complete source BEFORE registerService wakes powerd. */
	poll();
	if (fReal || fAdsp) {
		fLoop = IOWorkLoop::workLoop();
		fTimer = IOTimerEventSource::timerEventSource(this, &SweetBattery::timerFired);
		if (fLoop && fTimer && fLoop->addEventSource(fTimer) == kIOReturnSuccess) {
			fTimerAdded = true;
			fRunning = true;
			fTimer->setTimeoutMS(fAdsp ? 10000 : 30000);
#if defined(FUXI)
			if (fAdsp) {
				fNotify = new IOInterruptEventSource;
				if (fNotify && fNotify->init(this, &SweetBattery::adspChangedFired) &&
				    fLoop->addEventSource(fNotify) == kIOReturnSuccess) {
					fNotifyAdded = true;
					fNotify->enable();
					fuxi_adsp_battery_on_change(&SweetBattery::adspChanged, this);
					fNotify->interruptOccurred(NULL, NULL, 0);
				} else {
					OSSafeReleaseNULL(fNotify);
					IOLog("SWEET BATTERY: change event unavailable; periodic polling retained\n");
				}
			}
#endif
		} else {
			fReal = false;
#if defined(FUXI)
			if (fAdsp || fAdspShown) {
				FuxiAdspBattery unavailable;
				bzero(&unavailable, sizeof(unavailable));
				unavailable.stale = 1;
				unavailable.max_age_ms = FUXI_BATTERY_DEFAULT_MAX_AGE_MS;
				unavailable.soc_age_ms = unavailable.external_age_ms = unavailable.status_age_ms = ~0u;
				publishAdsp(unavailable);
			} else
#endif
				poll();
			IOLog("SWEET BATTERY: timer unavailable; %s\n",
			    fAdsp || fAdspShown ? "ADSP values retained, validity unknown" : "static fallback");
		}
	}
	registerService();
	return true;
}

void
SweetBattery::stop(IOService *provider)
{
#if defined(FUXI)
	fuxi_adsp_battery_on_change(NULL, NULL);
#endif
	if (fLoop && fTimerAdded) {
		/* Serialize against a running timer callback, including rearming. */
		(void)fLoop->runAction(&SweetBattery::stopPolling, this);
#if defined(FUXI)
		if (fNotifyAdded) {
			fLoop->removeEventSource(fNotify);
			fNotifyAdded = false;
		}
#endif
		fLoop->removeEventSource(fTimer);
		fTimerAdded = false;
	}
	IOPMPowerSource::stop(provider);
}

IOReturn
SweetBattery::stopPolling(OSObject *owner, void *, void *, void *, void *)
{
	SweetBattery *self = OSDynamicCast(SweetBattery, owner);
	if (!self) {
		return kIOReturnBadArgument;
	}
	self->fRunning = false;
#if defined(FUXI)
	if (self->fNotify) {
		self->fNotify->disable();
	}
#endif
	self->fTimer->cancelTimeout();
	self->fTimer->disable();
	return kIOReturnSuccess;
}

void
SweetBattery::free(void)
{
#if defined(FUXI)
	OSSafeReleaseNULL(fNotify);
#endif
	OSSafeReleaseNULL(fTimer);
	OSSafeReleaseNULL(fLoop);
	IOPMPowerSource::free();
}
#endif /* ARM64_BOARD_CONFIG_SWEET */
