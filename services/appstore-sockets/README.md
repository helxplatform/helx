# Appstore-Sockets 
Appstore-Sockets consists of a server and monitor application. Both of these applications follow the same versioning scheme as they are reasonably coupled together. 

These applications are used as part of a typical HeLx deployment enabling pod monitoring functionlity as part of the HeLx-UI sidebar and colored iconography. 

The applications are packaged in [appstore-sockets-chart](https://github.com/helxplatform/appstore-sockets-chart) and integrated with [helm-charts](https://github.com/helxplatform/helm-charts) which is used for helm deployments of HeLx.

## Makefile
Makefile is used to keep track of the version of the software and consists of a few easy to use make targets for building dev and production images locally.

## CI/CD
Github Actions is used to build and create release objects as well as test images when pushing to this repository. We use tagging to ensure our version is consistent and push to docker and Renci artifact repository for pairity. 