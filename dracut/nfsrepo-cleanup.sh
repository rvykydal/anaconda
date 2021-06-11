#!/bin/sh

type getargbool >/dev/null 2>&1 || . /lib/dracut-lib.sh

if getargbool 0 rd.live.ram -d -y live_ram; then
    while read -r src mnt fs rest || [ -n "$src" ]; do
        if [ "$mnt" = "/run/install/repo" ]; then
            if [ "$fs" = "nfs" ] || [ "$fs" = "nfs4" ]; then
                umount /run/install/repo
		break
            fi
        fi
    done < /proc/mounts
fi
