#!/usr/bin/env bash

# Compile all the subdirs applicable code to LLVM IR.
# lib/ will have errors, but are safe to ignore for our purposes.
#DIR=$PWD
#CC=wllvm

make binary -j || exit 1
#(cd src ; make -j) || exit 1

cd client ; make -j
chmod +x mosquitto_sub
chmod +x mosquitto_pub
