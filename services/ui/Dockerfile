###################
# Build environment
###################
FROM node:lts-bullseye-slim AS builder

ARG REACT_APP_WORKSPACES_ENABLED=true
ENV REACT_APP_WORKSPACES_ENABLED=$REACT_APP_WORKSPACES_ENABLED

# Copy and install requirements
WORKDIR /usr/src/app
COPY --chown=node:node "package*.json" /usr/src/app/
RUN npm install -g npm@latest
RUN npm clean-install

COPY --chown=node:node . /usr/src/app
RUN npm run build

########################
# Production environment
########################

FROM nginx:mainline-alpine-slim
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /usr/src/app/build/ /usr/share/nginx/static/
# RUN mv /usr/share/nginx/static/frontend/index.html /usr/share/nginx/html/

RUN apk upgrade
RUN apk add bash

WORKDIR /usr/src/app
COPY bin /usr/src/app/bin
ENV PATH="/usr/src/app/bin:${PATH}"

# UNCDSR-182: /usr/share/nginx/html is mounted wholesale as an emptyDir so
# the container's root filesystem can be read-only, which means it starts
# out empty on every boot. A subPath mount onto just index.html isn't viable
# here: Kubernetes subPath cannot cleanly replace a file that already exists
# in the image (confirmed directly against this exact image -- a minimal
# reproduction mounting emptyDir via subPath onto this path fails every
# time with "not a directory", while the identical mount onto a path that
# doesn't pre-exist in the image works immediately). Mounting the whole
# directory sidesteps that, but then nothing but index.html (which
# start_server/create_index regenerates every boot anyway) survives the
# fresh, empty mount -- in particular nginx's default 50x.html error page.
# This pristine, never-mounted-over backup is what start_server re-seeds
# the rest of the directory from before create_index writes index.html.
RUN cp -a /usr/share/nginx/html /usr/share/nginx/html.default

# Allow GID=0 to modify files/dirs.  Mainly for OpenShift but can be used
# elsewhere.
RUN chgrp -R 0 /usr/share/nginx && \
    chmod -R g=u /usr/share/nginx

EXPOSE 80
CMD ["start_server", "/usr/share/nginx/static/frontend/env.json"]