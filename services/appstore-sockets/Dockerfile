FROM node:22-alpine

WORKDIR /usr/src/app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

EXPOSE 5555
CMD ["npm", "start"]