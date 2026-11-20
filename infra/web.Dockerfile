# 프론트엔드 빌드 후 Nginx로 정적 파일 제공 + /api 프록시. 빌드 컨텍스트는 저장소 루트.
FROM node:24-alpine AS build
WORKDIR /web
RUN npm install -g pnpm@9
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# build가 아니라 build:backend: .env.backend의 VITE_API_MODE=real로 빌드해야 mock이 아니다.
RUN pnpm build:backend

FROM nginx:1.27-alpine
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
