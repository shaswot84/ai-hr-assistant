FROM node:22-alpine

WORKDIR /app

# Install dependencies. The compose file mounts the live source over /app and
# a named volume over /app/node_modules, so ensure deps exist on first start.
CMD ["sh", "-c", "if [ ! -d node_modules ] || [ -z \"$(ls -A node_modules)\" ]; then npm install; fi && npm run dev"]