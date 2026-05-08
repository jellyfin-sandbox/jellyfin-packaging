# Docker build arguments
ARG DOTNET_VERSION=8.0
ARG NODEJS_VERSION=20

ARG PACKAGE_TYPE=debian
ARG PACKAGE_VERSION=bookworm-20260505

FROM ${PACKAGE_TYPE}:${PACKAGE_VERSION}

ARG SOURCE_DIR=/jellyfin
ARG ARTIFACT_DIR=/dist
ARG DOTNET_VERSION
ARG NODEJS_VERSION
ARG PACKAGE_TYPE
ARG PACKAGE_VERSION

# Docker run environment
ENV SOURCE_DIR=/jellyfin
ENV ARTIFACT_DIR=/dist
ENV TYPE=${PACKAGE_TYPE}
ENV VERSION=${PACKAGE_VERSION}
ENV ARCHIVE_TYPES=targz

# Prepare Debian build environment
RUN apt-get update -y \
 && DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC \
    apt-get install --no-install-recommends -y \
    wget \
    unzip \
    git \
    debhelper \
    gnupg \
    devscripts \
    build-essential \
    git \
    mmv \
    lsb-release\
    zip \
    libssl*.* \
    liblttng-ust*\
    libssl-dev \
    libicu-dev \
    icu-devtools \
    libfontconfig*-dev \
    libcurl*openssl-dev \
    libfreetype*-dev \
 && apt-get clean autoclean -y \
 && apt-get autoremove -y \
 && rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/* \
 && git config --global --add safe.directory /jellyfin/jellyfin-web

# Prepare dotnet SDK
RUN wget https://packages.microsoft.com/config/${PACKAGE_TYPE}/${PACKAGE_VERSION}/packages-microsoft-prod.deb -O packages-microsoft-prod.deb \
 && dpkg -i packages-microsoft-prod.deb \
 && apt-get -f install \
 && apt-get update \
 && apt-get install -y dotnet-sdk-${DOTNET_VERSION}

# Prepare nodejs
RUN wget https://deb.nodesource.com/setup_${NODEJS_VERSION}.x -O nodejs-install.sh \
 && chmod +x ./nodejs-install.sh \
 && ./nodejs-install.sh \
 && apt-get install -y \
    nodejs

# Clean up dependencies
RUN apt-get clean autoclean -y \
 && apt-get autoremove -y \
 && rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/*

# Link to build script
RUN ln -sf ${SOURCE_DIR}/portable/build.sh /build.sh

VOLUME ${SOURCE_DIR}/

VOLUME ${ARTIFACT_DIR}/

ENTRYPOINT ["/build.sh"]
