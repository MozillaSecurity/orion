#!/bin/bash -ex

cd $HOME

function retry {
  for i in {1..10}; do "$@" && break || sleep 30; done
}

# Get fuzzmanager configuration from credstash
credstash get fuzzmanagerconf > .fuzzmanagerconf

# Update fuzzmanager config for this instance
mkdir -p signatures
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/signatures
tool = grizzly-$TOOLNAME
clientid = $(curl --retry 5 -s http://169.254.169.254/latest/meta-data/public-hostname)
EOF

eval "$(ssh-agent -s)"
mkdir -p .ssh
ssh-keyscan github.com >> .ssh/known_hosts

# Get deployment keys from credstash
credstash get deploy-grizzly.pem > .ssh/id_ecdsa.grizzly
credstash get deploy-grizzly-private.pem > .ssh/id_ecdsa.grizzly_private
credstash get deploy-loki.pem > .ssh/id_ecdsa.loki
credstash get deploy-sapphire.pem > .ssh/id_ecdsa.sapphire
credstash get deploy-domino.pem > .ssh/id_ecdsa.domino
credstash get deploy-fuzzidl.pem > .ssh/id_ecdsa.fuzzidl
chmod 0600 .ssh/id_*

# Setup Additional Key Identities
cat << EOF >> .ssh/config

Host grizzly
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/id_ecdsa.grizzly

Host grizzly-private
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/id_ecdsa.grizzly_private

Host loki
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/id_ecdsa.loki

Host sapphire
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/id_ecdsa.sapphire

Host domino
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/id_ecdsa.domino

Host fuzzidl
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/id_ecdsa.fuzzidl
EOF

# Checkout fuzzer including framework, install everything
retry pip install -U -r config/requirements.txt
retry git clone -v --depth 1 git@grizzly:MozillaSecurity/grizzly.git
retry git clone -v --depth 1 git@grizzly-private:MozillaSecurity/grizzly-private.git grizzly-private
cp -r grizzly-private/* grizzly

# Checkout Domato
if [ "$CORPMAN" = "domato" ]
then
  retry git clone -v --depth 1 https://github.com/google/domato.git
  patch domato/template.html grizzly/corpman/resources/domato/add_fuzzPriv.patch
  patch -d domato/ -i ../grizzly/corpman/resources/domato/grammar.patch
  #patch -d domato/ -i ../grizzly/corpman/resources/domato/add_mathml.patch
fi

if [ "$CORPMAN" = "domato-canvas" ]
then
  retry git clone -v --depth 1 https://github.com/google/domato.git
  patch domato/canvas/template.html grizzly/corpman/resources/domato/canvas-template.patch
fi

if [ "$CORPMAN" = "domato-js" ]
then
  retry git clone -v --depth 1 https://github.com/google/domato.git
  patch domato/jscript/generator.py grizzly/corpman/resources/domato/jsgen.patch
  patch domato/jscript/jscript.txt grizzly/corpman/resources/domato/jsgrammar.patch
  patch domato/jscript/template.html grizzly/corpman/resources/domato/jstemplate.patch
fi

# Checkout domino
if [ "$CORPMAN" = "domino" ]
then
  retry git clone -v --depth 1 git@domino:pyoor/DOMfuzz2.git domino
  (cd domino
   npm install -ddd
   npm run build
  )
fi

# Download Audio corpus
if [ "$CORPMAN" = "audio" ]
then
  mkdir grizzly/corpus
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/flac grizzly/corpus/flac/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/m4a-aac grizzly/corpus/m4a-aac/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/mp3 grizzly/corpus/mp3/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/wav grizzly/corpus/wav/
fi

# Download Image corpus
if [ "$CORPMAN" = "image" ]
then
  mkdir grizzly/corpus
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/bmp grizzly/corpus/bmp/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/gif grizzly/corpus/gif/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/ico grizzly/corpus/ico/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/jpg grizzly/corpus/jpg/
  #svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/png grizzly/corpus/png/
fi

# Download Video corpus
if [ "$CORPMAN" = "video" ]
then
  mkdir grizzly/corpus
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/mp4 grizzly/corpus/mp4/
  #svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/ogv grizzly/corpus/ogv/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/vp8 grizzly/corpus/vp8/common/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/vp9 grizzly/corpus/vp9/
  svn export https://github.com/mozillasecurity/fuzzdata.git/trunk/samples/webm grizzly/corpus/webm/
fi

# Refresh FM signatures
retry python -m Collector.Collector --refresh

# Download Target
if [ -z "$TARGET" ]
then
  TARGET="$(./targets/rand.py "$TOOLNAME")"
fi

if [ ! -z "$COVERAGE" ]
then
  export GCOV_PREFIX_STRIP=6
  export GCOV_PREFIX=~/firefox

  # pull down firefox and set permissions to allow for write
  retry fuzzfetch -n firefox --coverage
  chmod u+rwX,g+rX,o+rX firefox -R

  # pull down the source tree for grcov
  hg clone https://hg.mozilla.org/mozilla-central
  export revision=$(grep -Po "(?<=SourceStamp\=).*" ~/firefox/platform.ini)

  ( cd mozilla-central
    hg update -r $revision
  )
else
  retry fuzzfetch -n firefox $TARGET
  chmod 0755 firefox
fi

# Give other macros defaults if needed
i=$(echo "$FUZZPRIV" | tr '[:upper:]' '[:lower:]')
if [ ! -z "$FUZZPRIV" -a \( "$i" = "1" -o "$i" = "t" -o "$i" = "true" -o "$i" = "y" -o "$i" = "yes" -o "$i" = "on" \) ]
then
  retry git clone -v --branch legacy --depth 1 https://github.com/MozillaSecurity/fuzzpriv.git # for fuzzPriv extension
  FUZZPRIV=--extension=../fuzzpriv
else
  # false or unknown value
  FUZZPRIV=
fi

# 20% of the time enable accessibility
if [ ! -z "$A11Y_SOMETIMES" -a $((RANDOM % 5)) -eq 0 ]
then
  export GNOME_ACCESSIBILITY=1
fi

if [ ! -z "$ACCEPTED_EXTENSIONS" ]
then
  ACCEPTED_EXTENSIONS="--accepted-extensions $ACCEPTED_EXTENSIONS"
fi

if [ ! -z "$CACHE" ]
then
  CACHE="--cache $CACHE"
fi

if [ ! -z "$IGNORE" ]
then
  IGNORE="--ignore $IGNORE"
fi

if [ ! -z "$LAUNCH_TIMEOUT" ]
then
  LAUNCH_TIMEOUT="--launch-timeout $LAUNCH_TIMEOUT"
fi

if [ ! -z "$MEM_LIMIT" ]
then
  MEM_LIMIT="-m $MEM_LIMIT"
fi

if [ ! -z "$PREFS" ]
then
  PREFS="-p $PREFS"
fi

if [ ! -z "$RELAUNCH" ]
then
  RELAUNCH="--relaunch $RELAUNCH"
fi

if [ ! -z "$TIMEOUT" ]
then
  TIMEOUT="--timeout $TIMEOUT"
fi

if [ ! -z "$COVERAGE" ]
then
  GCOV_ITERATIONS="--gcov-iterations ${GCOV_ITERATIONS:=10}"
  RUNNER=~/config/coverage.sh
  INSTANCES=1
else
  RUNNER=~/config/forever.sh
fi

cd grizzly
screen -dmLS grizzly
sleep 5
screen -S grizzly -X screen ~/config/report_stats.sh
for i in $(seq 1 $INSTANCES)
do
  if [ $i -ne 1 ]; then sleep 30; fi # workaround for https://bugzilla.mozilla.org/show_bug.cgi?id=1386340
  screen -S grizzly -X screen $RUNNER python grizzly.py ../firefox/firefox $INPUT $CORPMAN $ACCEPTED_EXTENSIONS $CACHE $LAUNCH_TIMEOUT $MEM_LIMIT $PREFS $RELAUNCH $TIMEOUT $IGNORE $FUZZPRIV $GCOV_ITERATIONS --fuzzmanager --xvfb
done

# need to keep the container running
while true
do
    sleep 300
done
