#include <sys/ioctl.h>
#include <linux/fs.h>
#include <stdint.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#define GET_PIN _IOR(0xf5,14,uint32_t)
int main(int argc,char**argv){int result=0;for(int i=1;i<argc;i++){int fd=open(argv[i],O_RDONLY|O_CLOEXEC|O_NOFOLLOW);if(fd<0){printf("%s open error %s\n",argv[i],strerror(errno));result=1;continue;} uint32_t flags=0,moved=0;int a=ioctl(fd,FS_IOC_GETFLAGS,&flags);int ea=errno;int b=ioctl(fd,GET_PIN,&moved);int eb=errno;printf("%s flags_rc=%d flags=0x%x flags_error=%d pin_rc=%d moved=%u pin_error=%d\n",argv[i],a,flags,a?ea:0,b,moved,b?eb:0);if(a||b)result=1;close(fd);}return result;}