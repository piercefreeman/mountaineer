import React from "react";

interface DatabaseSetupPageProps {
  createdbCommand: string;
}

const DatabaseSetupPage = ({ createdbCommand }: DatabaseSetupPageProps) => {
  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-6">
      <div className="w-full max-w-2xl">
        <p className="text-xs font-medium uppercase tracking-[0.25em] text-neutral-400">
          Before you begin
        </p>

        <h1 className="mt-4 text-[clamp(2rem,5vw,3.5rem)] font-light leading-[1.1] tracking-tight text-black">
          Create your
          <br />
          database tables
        </h1>

        <p className="mt-6 max-w-md text-base leading-relaxed text-neutral-500">
          The scaffold needs its Postgres schema before pages can load server
          data. Run one command and you&apos;re ready.
        </p>

        <div className="mt-10 border-t border-neutral-200 pt-8">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-neutral-400">
            Terminal
          </p>
          <pre className="mt-3 font-mono text-lg tracking-tight text-black">
            <span className="select-none text-neutral-300">$ </span>
            {createdbCommand}
          </pre>
        </div>

        <p className="mt-8 text-sm text-neutral-400">
          Then refresh this page.
        </p>

        <div className="mt-16 border-t border-neutral-100 pt-8">
          <div className="space-y-4 text-sm leading-relaxed text-neutral-400">
            <p>
              <span className="text-neutral-600">createdb</span> reads your
              Iceaxe models and creates matching Postgres tables.
            </p>
            <p>
              If Postgres isn&apos;t running yet, start it first, then re-run
              the command.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DatabaseSetupPage;
