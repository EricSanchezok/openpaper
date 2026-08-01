ARG NODE_IMAGE=node:22-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3
FROM ${NODE_IMAGE} AS dependencies

WORKDIR /app
RUN corepack enable && corepack prepare yarn@1.22.22 --activate
COPY client/package.json client/yarn.lock /app/
RUN yarn install --frozen-lockfile

FROM dependencies AS builder

ARG NEXT_PUBLIC_API_URL=
ARG NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=
ARG NEXT_PUBLIC_POSTHOG_KEY=
ARG NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
ARG NEXT_PUBLIC_RELEASE_SHA=development
ARG NEXT_PUBLIC_RUM_APPLICATION_ID=
ARG NEXT_PUBLIC_RUM_GUEST_ROLE_ARN=
ARG NEXT_PUBLIC_RUM_IDENTITY_POOL_ID=
ARG NEXT_PUBLIC_RUM_REGION=
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=${NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY} \
    NEXT_PUBLIC_POSTHOG_KEY=${NEXT_PUBLIC_POSTHOG_KEY} \
    NEXT_PUBLIC_POSTHOG_HOST=${NEXT_PUBLIC_POSTHOG_HOST} \
    NEXT_PUBLIC_RELEASE_SHA=${NEXT_PUBLIC_RELEASE_SHA} \
    NEXT_PUBLIC_RUM_APPLICATION_ID=${NEXT_PUBLIC_RUM_APPLICATION_ID} \
    NEXT_PUBLIC_RUM_GUEST_ROLE_ARN=${NEXT_PUBLIC_RUM_GUEST_ROLE_ARN} \
    NEXT_PUBLIC_RUM_IDENTITY_POOL_ID=${NEXT_PUBLIC_RUM_IDENTITY_POOL_ID} \
    NEXT_PUBLIC_RUM_REGION=${NEXT_PUBLIC_RUM_REGION} \
    UPLOAD_SOURCE_MAPS=true \
    NEXT_TELEMETRY_DISABLED=1

COPY client/ /app/
RUN yarn build
RUN mkdir -p /tmp/scholens-source-maps \
    && find .next -type f -name '*.map' -exec cp --parents '{}' /tmp/scholens-source-maps/ \;

FROM ${NODE_IMAGE} AS runtime

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/public /app/public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone /app/
COPY --from=builder --chown=nextjs:nodejs /app/.next/static /app/.next/static
# Kept outside the served application tree so CI can extract the exact maps
# corresponding to this immutable image without publishing them to browsers.
COPY --from=builder --chown=root:root /tmp/scholens-source-maps /opt/scholens-source-maps

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
