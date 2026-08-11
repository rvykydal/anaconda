rm -rf ./result
make -f ./Makefile.am container-rpms-scratch
#ANACONDA_WEBUI_PR=1161 COCKPIT_PR=23341 make -f ./Makefile.am container-webui-iso-build
sudo make -f ./Makefile.am anaconda-iso-creator-build
COCKPIT_PR=23341 make -f ./Makefile.am container-webui-iso-build
