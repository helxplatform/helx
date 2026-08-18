FROM node:20-alpine

WORKDIR /usr/src/app

# Copy just these for caching npm ci
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

EXPOSE 5555
CMD ["npm", "start"]