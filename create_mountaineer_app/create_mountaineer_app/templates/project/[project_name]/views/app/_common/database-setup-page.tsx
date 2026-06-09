{% raw %}
import React from "react";
import { Background, Masthead } from "./field-guide";

interface DatabaseSetupPageProps {
  createdbCommand: string;
}

const DatabaseSetupPage = ({ createdbCommand }: DatabaseSetupPageProps) => {
  return (
    <>
      <Background />
      <div className="fg-wrap">
        <Masthead />

        <main className="fg-hero-main">
          <div className="fg-eyebrow fg-rise" style={{ animationDelay: "0.05s" }}>
            <span className="fg-dot" />
            <span>One-time setup</span>
          </div>

          <h1 className="fg-display fg-rise" style={{ animationDelay: "0.1s", fontSize: "clamp(44px, 7vw, 80px)" }}>
            Set up your
            <br />
            <span className="fg-pine">database.</span>
          </h1>

          <p className="fg-lede fg-rise" style={{ animationDelay: "0.24s" }}>
            Your Postgres schema isn&apos;t built yet. Run one command to create
            the tables from your Iceaxe models, then refresh this page.
          </p>

          <div className="fg-rise" style={{ animationDelay: "0.32s", marginTop: "32px", maxWidth: "640px" }}>
            <span className="fg-tag">Terminal</span>
            <div className="fg-terminal">
              <span className="fg-prompt">$ </span>
              {createdbCommand}
            </div>
          </div>

          <p className="fg-rise" style={{ animationDelay: "0.4s", marginTop: "18px", fontSize: "13px", color: "var(--muted)" }}>
            Postgres not running? Start it first, then re-run the command.
          </p>
        </main>

        <div className="fg-rule" />
        <footer className="fg-foot">
          <span className="fg-foot-l">
            <code>createdb</code> reads your Iceaxe models
          </span>
          <span className="fg-foot-r">37.9235° N · 122.5965° W</span>
        </footer>
      </div>
    </>
  );
};

export default DatabaseSetupPage;
{% endraw %}
