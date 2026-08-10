# Build the bundle, then throw the toolchain away. The result is nginx plus a
# directory of static files — there is no Node process in production, which is
# what R12 (revised) means by "the frontend needs no server at all".
#
# Build context is the repo root, not apps/web: nginx/nginx.conf has to come in
# too, and a second copy of it would drift from the one it is meant to mirror.

FROM node:26-alpine AS build

WORKDIR /srv

# Copied before the source so a source edit does not re-run the install.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web/tsconfig.json apps/web/vite.config.ts apps/web/index.html ./
COPY apps/web/src ./src

# `npm run build` typechecks first. A type error becomes a failed image rather
# than a broken page — the only place that check has teeth, since nothing runs
# tsc in production.
RUN npm run build


FROM nginx:1.27-alpine

COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /srv/dist /usr/share/nginx/html

EXPOSE 80
