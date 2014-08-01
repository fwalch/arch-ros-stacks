#!/bin/bash

get_pkgbuild()
{
    source $1
    echo "pkgname=$pkgname"
    echo "depends=( ${ros_depends[@]} ${ros_makedepends[@]} )"
}

get_version()
{
    source $1
    printf "%s-%s" "$pkgver" "$pkgrel"
}

get_makepkg_conf()
{
    source /etc/makepkg.conf
    echo "pkgdest=${PKGDEST-.}"
    echo "pkgext=${PKGEXT-.pkg.tar.xz}"
}

msg()
{
    local mesg=$1; shift
    local ALL_OFF="$(tput sgr0)"
    local BOLD="$(tput bold)"
    local GREEN="${BOLD}$(tput setaf 2)"
    printf "${GREEN}==>${ALL_OFF}${BOLD} ${mesg}${ALL_OFF}\n" "$@" >&2
}

usage()
{
    echo "usage: $(basename "$0") [option] rosdistro"
    echo
    echo "    --force - force rebuilding all packages"
    exit
}

# Argument parsing
packageargs=()
while [[ $1 ]]; do
    case "$1" in
        '--force'|'-f') force='1' ;;
        # '--ignore') ignorearg="$2" ; PACOPTS+=("--ignore" "$2") ; shift ;;
        # '--') shift ; packageargs+=("$@") ; break ;;
        -*) echo "$0: Option \`$1' is not valid." ; exit 5 ;;
        groovy*) dir="groovy" ;;
        hydro*)  dir="hydro"  ;;
        indigo*) dir="indigo" ;;
    esac
    shift
done
[[ $dir ]] || usage

makepkgopts+=("--asdeps" "--noconfirm")
# [[ $force ]] && makepkgopts+=("--force") || makepkgopts+=("--needed")
[[ $force ]] || makepkgopts+=("--needed")

#TODO tsort deps
# dependencies=$(find "./dependencies" -name PKGBUILD)
# for dependency in ${dependencies[@]}; do
#     pushd "${dependency%/*}" > /dev/null
#     source <(get_pkgbuild PKGBUILD)
#     makepkg -si "${makepkgopts[@]}"
#     retcode=$?
#     popd > /dev/null
#     [[ $retcode -ne 0 ]] && exit $retcode
# done

tmp=$(mktemp)
pkgbuilds=$(find "$dir" -name PKGBUILD)
for pkgbuild in ${pkgbuilds[@]}; do
    source <(get_pkgbuild $pkgbuild)
    for depend in ${depends[@]}; do
        printf "%s %s\n" "$depend" "$pkgname" >> $tmp
    done
done

sorted=( $(tsort $tmp) )

source <(get_makepkg_conf)
for pkgname in ${sorted[@]}; do
    pkgdir=${pkgname#ros-hydro-}
    pkgdir=${pkgdir//-/_}
    pushd "$dir"/$pkgdir > /dev/null
    ver=$(get_version ./PKGBUILD)
    retcode=0
    if [[ ! -e ignore ]]; then
        pkgs=( $(ls --reverse *$pkgext 2> /dev/null) )
        makepkg -si "${makepkgopts[@]}"
        retcode=$?
        # remove old pkgs
        [[ -n "${pkgs[@]:1}" ]] && rm ${pkgs[@]:1}
    fi
    popd > /dev/null
    [[ $retcode -ne 0 ]] && exit $retcode
done
