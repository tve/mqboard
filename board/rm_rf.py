# rf -rf : deletes all files in the flash filesystem
import uos
def rmdir(dir):
    for f in uos.ilistdir(dir):
        if f[1] == 0x4000:
            rmdir(dir+"/"+f[0])
        else:
            uos.remove(f[0])
    if dir != "/":
        uos.rmdir(dir)
rmdir("/")
