# Image environment
FROM g2inc/oif-python


MAINTAINER Screaming_Bunny

LABEL name="HTTPS Transport Module" \
vendor="OpenC2" \
license="BSD" \
version="2.0" \
description="This is the HTTPS Transport Module container"

ADD requirements.txt /tmp/requirements.txt
ADD HTTPS/ /opt/transport/HTTPS
ADD entrypoint.sh /entrypoint.sh
ADD docker_dev_start.sh /opt/transport/dev_start.sh

# Set working directory
WORKDIR /opt/transport

# Requirements install
RUN apk update && \
  apk add --no-cache \
  bash \
  openssl && \
  pip3 install -r /tmp/requirements.txt && \
  rm -r /root/.cache && \
  chmod +x /entrypoint.sh && \
  chmod +x /opt/transport/dev_start.sh && \
  chmod +w /opt/transport/HTTPS/certs && \
  dos2unix /entrypoint.sh && \
  dos2unix /opt/transport/dev_start.sh && \
#
# Cleanup
apk del tar && \
rm /var/cache/apk/* && \
rm -rf *.tar.gz* /usr/src /root/.gnupg /tmp/*

ENTRYPOINT ["/entrypoint.sh"]

# Run command when container launches
CMD ["./dev_start.sh"]

