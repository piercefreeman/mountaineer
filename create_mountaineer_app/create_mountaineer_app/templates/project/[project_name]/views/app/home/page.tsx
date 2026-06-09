{% if create_stub_files %}
{% raw %}
import React from "react";
import DatabaseSetupPage from "../_common/database-setup-page";
import { Background, Masthead } from "../_common/field-guide";
import { useServer } from "./_server/useServer";

const Chevron = () => (
  <svg className="fg-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="m9 18 6-6-6-6" />
  </svg>
);

const Home = () => {
  const serverState = useServer();

  if (serverState.database_setup_required) {
    return (
      <DatabaseSetupPage
        createdbCommand={serverState.database_setup_required.createdb_command}
      />
    );
  }

  const items = serverState.items;
  const count = items.length;

  return (
    <>
      <Background />
      <div className="fg-wrap">
        <Masthead />

        <div className="fg-split">
          <section className="fg-hero">
            <div className="fg-eyebrow fg-rise" style={{ animationDelay: "0.05s" }}>
              <span className="fg-dot" />
              <span>Server-rendered &amp; live</span>
            </div>

            <h1 className="fg-display">
              <span className="fg-rise" style={{ display: "block", animationDelay: "0.1s" }}>
                Move fast.
              </span>
              <span className="fg-rise fg-pine" style={{ display: "block", animationDelay: "0.18s" }}>
                Climb mountains.
              </span>
            </h1>

            <p className="fg-lede fg-rise" style={{ animationDelay: "0.28s" }}>
              Your app is on the map. This page is rendered from{" "}
              <code>controllers/home.py</code>, and will update dynamically when
              you take an action.
            </p>

            <div className="fg-cta fg-rise" style={{ animationDelay: "0.36s" }}>
              <button
                className="fg-btn fg-primary"
                type="button"
                onClick={async () => {
                  await serverState.new_detail({ signal: undefined });
                }}
              >
                Pitch a new task
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>
              <a
                className="fg-btn fg-ghost"
                href="https://github.com/piercefreeman/mountaineer#readme"
                target="_blank"
                rel="noreferrer"
              >
                Read the guide
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M7 17 17 7M8 7h9v9" />
                </svg>
              </a>
            </div>
          </section>

          <aside className="fg-tasks fg-rise" style={{ animationDelay: "0.2s" }}>
            <div className="fg-tasks-head">
              <h2>The route ahead</h2>
              <span className="fg-badge">
                {count} {count === 1 ? "task" : "tasks"}
              </span>
            </div>

            {count === 0 ? (
              <div className="fg-empty">
                <div className="fg-empty-title">No tasks yet</div>
                <p>Pitch your first task to start the climb.</p>
              </div>
            ) : (
              <div className={count > 1 ? "fg-trail fg-has-line" : "fg-trail"}>
                {items.map((item, index) => (
                  <a
                    key={item.id}
                    className="fg-wp"
                    href={serverState.linkGenerator.detailController({
                      detail_id: item.id!,
                    })}
                  >
                    <span className="fg-node">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="fg-wp-body">
                      <div className="fg-desc">{item.description}</div>
                      <div className="fg-elev">
                        +{((index + 1) * 1200).toLocaleString()} m gain
                      </div>
                    </span>
                    <Chevron />
                  </a>
                ))}
              </div>
            )}
          </aside>
        </div>

        <div className="fg-rule" />
        <footer className="fg-foot">
          <span className="fg-foot-l">
            Edit <code>views/app/home/page.tsx</code>
          </span>
          <span className="fg-foot-r">37.9235° N · 122.5965° W</span>
        </footer>
      </div>
    </>
  );
};

export default Home;
{% endraw %}
{% endif %}
