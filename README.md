# Khidmati AI-First Marketplace MVP

A deployable React + TypeScript + Vite MVP for a two-sided home-services marketplace.

## Implemented

- Customer and professional role switching
- AI-guided service request creation
- Local AI classification, urgency, price-range, safety, and follow-up suggestions
- Persistent browser storage for jobs and bids
- Professional job marketplace and AI-assisted bid drafting
- Bid ranking, comparison, acceptance, warranties, and trust indicators
- Job lifecycle: booked, on the way, in progress, awaiting confirmation, completed
- In-app messaging with AI scope summary
- Structured mutual review flow
- Responsive customer, professional, profile, messages, and job views
- Vercel SPA deployment configuration

## Run

```bash
npm install
npm run dev
```

## Production build

```bash
npm run build
npm run preview
```

## Deploy to Vercel

Import the repository in Vercel. Framework preset: **Vite**. Build command: `npm run build`. Output directory: `dist`.

## Important production integrations

The packaged MVP is a functional frontend with browser persistence. Before accepting real users or payments, connect:

- Supabase Auth, Postgres, Storage, and Realtime
- A server-side AI endpoint; never expose a private AI key in Vite client code
- A Jordan/MENA-supported payment provider with marketplace payouts
- Government ID and professional verification provider
- Maps/geocoding and notification providers
- Server-side authorization, audit logs, rate limits, moderation, and dispute operations

Copy `.env.example` to `.env.local` when integrations are added.
