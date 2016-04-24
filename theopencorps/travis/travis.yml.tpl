{% if environment == "container" %}
# Container based architecture (faster boots, 4GB RAM)
sudo: false
{% elif environment == "trusty" %}
# Trusty (beta) - slower to boot but 7.5GB RAM
sudo: required
dist: trusty
{% endif %}

# For now, we limit to Python 2.7
language: python
python:
  - '2.7'

env:
{% if secure_variables %}
  global:
{% for variable in secure_variables %}
    - secure: "{{variable}}"
{% endfor %}
{% for variable in environment_variables %}
    - {{variable}}
{% endfor %}
{% endif %}
  matrix:
{% if quartus %}
    - QUARTUS_SYNTHESIS=true
{% endif %}
{% if cocotb %}
    - COCOTB_SIMULATION=true
{% endif %}
{% if vunit and fusesoc %}
    - VUNIT_FUSESOC_SIMULATION=true
{% elif vunit %}
    - VUNIT_SIMULATION=true
{% endif %}

{% if modelsim %}
before_install:
  - sudo dpkg --add-architecture i386
  - sudo apt-get update
  - sudo apt-get install -y build-essential
  - sudo apt-get install -y gcc-multilib g++-multilib lib32z1 lib32stdc++6 lib32gcc1 expat:i386 fontconfig:i386 libfreetype6:i386 libexpat1:i386 libc6:i386 libgtk-3-0:i386 libcanberra0:i386 libpng12-0:i386 libice6:i386 libsm6:i386 libncurses5:i386 zlib1g:i386 libx11-6:i386 libxau6:i386 libxdmcp6:i386 libxext6:i386 libxft2:i386 libxrender1:i386 libxt6:i386 libxtst6:i386
{% endif %}

install:
{% if fusesoc %}
  - pip install git+git://github.com/chiggs/fusesoc
{% endif %}
{% if vunit %}
  - pip install git+git://github.com/LarsAsplund/vunit
{% endif %}
  - git clone https://github.com/potentialventures/buildtools

script:
  - ./buildtools/travis/build.sh
