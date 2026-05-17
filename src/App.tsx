import { AlertCircle, CalendarDays, Shield, Trophy } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

type Champion = {
  titleName: string;
  championName: string;
  imageUrl: string;
  championshipDate: string | null;
  daysAsChampion: number | null;
  lastDefenseDate: string | null;
  daysSinceLastDefense: number | null;
  source?: {
    wweUrl?: string;
    cagematchUrl?: string;
  };
};

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; champions: Champion[] }
  | { status: 'empty' }
  | { status: 'error'; message: string };

const NO_DEFENSE = 'No Title Defenses Yet';

function isChampion(value: unknown): value is Champion {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  return typeof item.titleName === 'string' && typeof item.championName === 'string';
}

function formatValue(value: string | number | null | undefined, fallback = 'Unavailable') {
  if (value === null || value === undefined || value === '') return fallback;
  return value;
}

function ChampionImage({ champion }: { champion: Champion }) {
  const [failed, setFailed] = useState(!champion.imageUrl);

  if (failed) {
    return (
      <div className="flex aspect-[4/3] items-center justify-center bg-[radial-gradient(circle_at_50%_18%,rgba(216,167,47,0.28),transparent_34%),linear-gradient(145deg,#202024,#111113)]">
        <Trophy className="h-14 w-14 text-gold-300/80" aria-hidden="true" />
      </div>
    );
  }

  return (
    <img
      src={champion.imageUrl}
      alt={`${champion.championName} official WWE profile headshot`}
      className="aspect-[4/3] w-full object-cover object-top"
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

function StatRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-4 border-t border-white/8 py-3 text-sm">
      <dt className="font-semibold text-zinc-200">{label}</dt>
      <dd className="max-w-[12rem] truncate text-right text-zinc-400" title={String(formatValue(value))}>
        {formatValue(value)}
      </dd>
    </div>
  );
}

function ChampionCard({ champion }: { champion: Champion }) {
  const lastDefense = champion.lastDefenseDate || NO_DEFENSE;
  const daysSinceDefense =
    lastDefense === NO_DEFENSE ? NO_DEFENSE : formatValue(champion.daysSinceLastDefense);

  return (
    <article className="group overflow-hidden rounded-lg border border-white/10 bg-ink-850 shadow-card transition duration-200 hover:-translate-y-0.5 hover:border-white/20">
      <ChampionImage champion={champion} />
      <div className="space-y-5 p-4">
        <div className="space-y-3">
          <div className="flex min-h-9 items-start gap-2">
            <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-gold-300/25 bg-gold-500/10 text-gold-300">
              <Shield className="h-4 w-4" aria-hidden="true" />
            </span>
            <h2 className="text-pretty text-sm font-semibold leading-5 text-zinc-100">
              {champion.titleName}
            </h2>
          </div>
          <p className="text-balance text-2xl font-semibold leading-tight text-white">
            {champion.championName}
          </p>
        </div>

        <dl>
          <StatRow label="Championship Date" value={champion.championshipDate} />
          <StatRow label="Days as Champion" value={champion.daysAsChampion} />
          <StatRow label="Last Defense Date" value={lastDefense} />
          <StatRow label="Days Since Last Defense" value={daysSinceDefense} />
        </dl>
      </div>
    </article>
  );
}

function StatusPanel({ state }: { state: Exclude<LoadState, { status: 'ready' }> }) {
  const copy = {
    loading: {
      title: 'Loading champions',
      message: 'Reading the local champions cache.',
    },
    empty: {
      title: 'No champions found',
      message: 'Run the scraper to populate public/champions.json.',
    },
    error: {
      title: 'Could not load champions',
      message: state.status === 'error' ? state.message : 'The cache could not be read.',
    },
  }[state.status];

  return (
    <div className="rounded-lg border border-white/10 bg-ink-850 p-6 text-zinc-300">
      <div className="mb-3 flex items-center gap-3 text-white">
        <AlertCircle className="h-5 w-5 text-gold-300" aria-hidden="true" />
        <h2 className="text-lg font-semibold">{copy.title}</h2>
      </div>
      <p>{copy.message}</p>
    </div>
  );
}

export function App() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;

    async function loadChampions() {
      try {
        const response = await fetch('/champions.json', { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`Cache request failed with HTTP ${response.status}.`);
        }

        const data: unknown = await response.json();
        if (!Array.isArray(data) || !data.every(isChampion)) {
          throw new Error('public/champions.json is not a valid champion array.');
        }

        if (!cancelled) {
          setState(data.length > 0 ? { status: 'ready', champions: data } : { status: 'empty' });
        }
      } catch (error) {
        if (!cancelled) {
          setState({
            status: 'error',
            message: error instanceof Error ? error.message : 'Unexpected cache parsing error.',
          });
        }
      }
    }

    loadChampions();
    return () => {
      cancelled = true;
    };
  }, []);

  const championCount = state.status === 'ready' ? state.champions.length : 0;
  const subtitle = useMemo(() => {
    if (state.status !== 'ready') return 'Local cache driven champion intelligence';
    return `${championCount} active championship ${championCount === 1 ? 'record' : 'records'}`;
  }, [championCount, state.status]);

  return (
    <main className="min-h-screen bg-ink-950 text-white">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-5 border-b border-white/10 pb-6 md:flex-row md:items-end md:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-zinc-400">
              <CalendarDays className="h-3.5 w-3.5 text-gold-300" aria-hidden="true" />
              Weekly Cache
            </div>
            <div>
              <h1 className="text-3xl font-semibold tracking-normal text-white sm:text-4xl">
                WWE Champions
              </h1>
              <p className="mt-2 text-sm text-zinc-400 sm:text-base">{subtitle}</p>
            </div>
          </div>
          <div className="grid w-full grid-cols-2 gap-2 sm:w-auto">
            <div className="rounded-lg border border-white/10 bg-ink-900 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Cache</p>
              <p className="mt-1 text-sm font-semibold text-zinc-100">champions.json</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-ink-900 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Source</p>
              <p className="mt-1 text-sm font-semibold text-zinc-100">WWE + Cagematch</p>
            </div>
          </div>
        </header>

        {state.status === 'ready' ? (
          <section
            aria-label="Current champions"
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
          >
            {state.champions.map((champion) => (
              <ChampionCard key={`${champion.titleName}-${champion.championName}`} champion={champion} />
            ))}
          </section>
        ) : (
          <StatusPanel state={state} />
        )}
      </div>
    </main>
  );
}
