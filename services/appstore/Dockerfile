FROM python:3.12.16-alpine

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Least privilege: Run as a non-root user.
ENV USER=appstore
ENV APP_HOME=/usr/src/inst-mgmt
ENV HOME=/home/$USER
ENV UID=1000

RUN mkdir $APP_HOME

RUN set -x && \
    apk upgrade --no-cache && \
    apk add --no-cache make git bash build-base xmlsec libxml2-dev linux-headers openssl && \
    adduser -D -s /bin/bash -h $HOME -u $UID $USER && \
    chown -R $UID:$UID $APP_HOME

# Removing but leaving commented in case Tycho needs this for swagger.
# Version 3.3.1 currently, if not complaints v3.3.3 this can be 
# completely removed. 
# RUN curl -sL https://deb.nodesource.com/setup_14.x | bash
# RUN apt-get install -y nodejs

WORKDIR $APP_HOME
COPY --chown=$UID:$UID . .

RUN chown -R $USER:0 $APP_HOME && \
    chmod -R g+w $APP_HOME

RUN if [ -d whl -a "$(ls -A whl/*.whl)" ]; then pip install whl/*.whl; fi
RUN export SET_BUILD_ENV_FROM_FILE=false \
    && pip install --upgrade "setuptools>=78.1.1" \
    && pip install "cython<3.0.0" "wheel>=0.46.2" \
    && pip install "pyyaml==5.4.1" --no-build-isolation \
    && make install \
    && unset SET_BUILD_ENV_FROM_FILE

# Fail the build, not the deploy, when a model change is missing its
# committed migration file. SECRET_KEY/DJANGO_SETTINGS_MODULE are throwaway
# values needed only to import settings; no database or cluster is required.
# Importing settings unconditionally opens log/*.log (base.py's LOGGING dict
# defines those handlers regardless of USE_LOG_FILE), which would otherwise
# bake root-owned log files into the image that the non-root runtime user
# can't write to -- remove them so log/ ships exactly as committed.
RUN SECRET_KEY=build-check DEV_PHASE=stub DJANGO_SETTINGS_MODULE=appstore.settings.helx_settings make check-migrations \
    && rm -f log/*.log

USER $USER

EXPOSE 8000
CMD ["make","start"]
