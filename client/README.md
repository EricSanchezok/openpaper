# Client

This server manages the frontend for the Scholens project, which allows users to upload, chat with, annotate, and manage research papers in one place.

First, ensure you've started the backend server. See `/server` for details.

For a fresh setup, run:

```bash
cp ../.env.example .env.local
corepack yarn go
```

Open [http://127.0.0.1:7303](http://127.0.0.1:7303) with your browser to use
the legacy comparison app. New product work belongs in `web/` on port 7300.

## Development
To run the development server, use:

```bash
corepack yarn dev
```

The command uses the fixed loopback port 7303 and fails if that port is already
occupied.
