#!/bin/bash
# In installer environment, after starting the installer run:
# sudo mount -o loop <EROFS_IMAGE> /run/install/sources/mount-0000-live_os_image/usr/share/anaconda/pixmaps/cloud

IMAGE_NAME="${1:-erofs-image}"
CORRUPTED_IMAGE_NAME="corrupted-${IMAGE_NAME}"
ROOT_DIR=${IMAGE_NAME}-root

FILE_PATH=/bigfile
DIR=$(dirname ${FILE_PATH})
mkdir -p /tmp/${ROOT_DIR}${DIR}
python3 -c "import sys; sys.stdout.buffer.write(b'Hello Fedora' * 700000)" > /tmp/${ROOT_DIR}${FILE_PATH}
mkfs.erofs -z lz4 /tmp/${IMAGE_NAME} /tmp/${ROOT_DIR}
cp /tmp/${IMAGE_NAME} /tmp/${CORRUPTED_IMAGE_NAME}
dd if=/dev/urandom of=/tmp/${CORRUPTED_IMAGE_NAME} bs=4096 seek=3 count=1 conv=notrunc

