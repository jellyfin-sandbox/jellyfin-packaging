ARG BASE_IMAGE

FROM ${BASE_IMAGE}
ARG BASE_MANIFEST_DIGEST

COPY mkimage.sh /mkimage.sh
RUN chmod +x /mkimage.sh && /mkimage.sh && rm /mkimage.sh

LABEL BASE_MANIFEST_DIGEST="${BASE_MANIFEST_DIGEST}"
