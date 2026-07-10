FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# Where your gateway lives — override with `docker run -e GATEWAY_URL=...`.
ENV GATEWAY_URL=http://localhost:8080

EXPOSE 80
