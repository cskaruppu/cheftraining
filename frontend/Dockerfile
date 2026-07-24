FROM node:22-alpine AS build
WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

# Unprivileged nginx (listens on 8080) — required for OpenShift's
# restricted SCC, which runs containers as a random non-root UID.
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
