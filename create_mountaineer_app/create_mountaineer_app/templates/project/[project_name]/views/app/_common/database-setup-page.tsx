import React from "react";

interface DatabaseSetupPageProps {
  createdbCommand: string;
}

const DatabaseSetupPage = ({ createdbCommand }: DatabaseSetupPageProps) => {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_#fff7ed,_#fffbeb_45%,_#f8fafc_100%)] px-6 py-12 text-slate-900">
      <div className="mx-auto flex min-h-[calc(100vh-6rem)] max-w-4xl items-center">
        <div className="w-full overflow-hidden rounded-[32px] border border-amber-200/70 bg-white/90 shadow-[0_30px_80px_-40px_rgba(120,53,15,0.45)] backdrop-blur">
          <div className="border-b border-amber-100 bg-amber-50/80 px-8 py-5">
            <p className="text-sm font-semibold uppercase tracking-[0.3em] text-amber-700">
              Database Setup Required
            </p>
          </div>

          <div className="grid gap-10 px-8 py-10 lg:grid-cols-[1.2fr_0.8fr] lg:px-10">
            <div>
              <h1 className="max-w-2xl font-serif text-4xl leading-tight text-slate-950 md:text-5xl">
                This app can&apos;t render yet because its database tables
                haven&apos;t been created.
              </h1>
              <p className="mt-4 max-w-xl text-base leading-7 text-slate-600">
                The CMA scaffold expects the initial schema to exist before the
                home and detail pages can load their server data.
              </p>

              <div className="mt-8 rounded-3xl bg-slate-950 p-5 text-sm text-slate-100 shadow-inner">
                <p className="mb-3 font-medium text-slate-400">
                  Run this command from the project root:
                </p>
                <code className="block overflow-x-auto font-mono text-[15px] text-emerald-300">
                  {createdbCommand}
                </code>
              </div>

              <p className="mt-5 text-sm text-slate-500">
                After the command succeeds, refresh this page.
              </p>
            </div>

            <div className="rounded-[28px] border border-slate-200 bg-slate-50 p-6">
              <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-500">
                What This Does
              </p>
              <div className="mt-6 space-y-4 text-sm leading-6 text-slate-600">
                <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200/70">
                  `createdb` inspects your Iceaxe models and creates the backing
                  Postgres tables.
                </div>
                <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200/70">
                  Without those tables, the scaffolded pages do not have valid
                  server values to hydrate.
                </div>
                <div className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200/70">
                  If Postgres is not running yet, start it first and then rerun
                  the command above.
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DatabaseSetupPage;
