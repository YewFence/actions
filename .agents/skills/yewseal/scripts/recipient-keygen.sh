# Generate an Age key pair for a new YewSeal recipient.
#
# The private key goes straight to the clipboard (first available platform
# helper) and its file is deleted on exit; the public key lands in /tmp for
# registry registration. Nothing secret reaches stdout: it carries the
# public-key path only. Usage: sh recipient-keygen.sh <alias>
set -eu
umask 077

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <alias>" >&2
  exit 2
fi

alias_name=$1
case $alias_name in
  ''|*[!A-Za-z0-9_-]*)
    echo "alias may only use letters, digits, hyphens, and underscores: $alias_name" >&2
    exit 2
    ;;
esac

command -v age-keygen >/dev/null || { echo "age-keygen not found" >&2; exit 1; }

# Plain calls, no exec: the process must stay this shell so the EXIT trap
# still deletes the key file.
copy_to_clipboard() {
  if command -v wl-copy >/dev/null 2>&1; then wl-copy
  elif command -v xclip >/dev/null 2>&1; then xclip -selection clipboard -in
  elif command -v xsel >/dev/null 2>&1; then xsel --clipboard --input
  elif command -v pbcopy >/dev/null 2>&1; then pbcopy
  elif command -v clip.exe >/dev/null 2>&1; then clip.exe
  else
    echo "no clipboard helper found; install wl-clipboard or xclip on Linux, or copy the key manually per the private-keys guide" >&2
    return 1
  fi
}

pub="/tmp/yews-$alias_name.pub"
keydir=$(mktemp -d "/tmp/yews-$alias_name.key.XXXXXX")
key="$keydir/identity"
trap 'rm -f "$key"; rmdir "$keydir"' EXIT

age-keygen -o "$key"
grep '^AGE-SECRET-KEY-' "$key" | copy_to_clipboard
age-keygen -y "$key" > "$pub"

echo "private key: in the clipboard; paste it into the password manager now"
echo "public key: $pub"
