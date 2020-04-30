# rf -rf : deletes all files in the flash filesystem
import uos
def rmdir(dir):
    print("rmdir contents:", dir)
    for f in uos.ilistdir(dir):
        if f[1] == 0x4000:
            rmdir(dir+"/"+f[0])
        else:
            print("rm", dir + '/' + f[0])
            uos.remove(dir + '/' + f[0])
    if dir != "/" and dir != "":
        print("rmdir", dir)
        uos.rmdir(dir)
rmdir("") # empty string is same as '/' and prevents issues with '//' in paths
