#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

pushd "$HOME"

# Add vimrc for Bionic
cat << EOF > .vimrc
:syntax enable
syntax on
set number
set ruler
set nocompatible
set bs=2
fixdel
set nowrap
set tabstop=4
set autoindent
set term=xterm
set smartindent
set showmode showcmd
set shiftwidth=4
set expandtab
set backspace=indent,eol,start
set hls
au BufNewFile,BufRead *.* exec 'match Error /\%119v/'
set paste
EOF

popd
