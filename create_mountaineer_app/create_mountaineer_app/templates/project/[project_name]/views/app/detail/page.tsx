{% if create_stub_files %}
{% raw %}
import React, { useState } from "react";
import DatabaseSetupPage from "../_common/database-setup-page";
import { Background, Masthead } from "../_common/field-guide";
import { useServer } from "./_server/useServer";

const Page = () => {
  const serverState = useServer();
  const [text, setText] = useState("");

  if (serverState.database_setup_required) {
    return (
      <DatabaseSetupPage
        createdbCommand={serverState.database_setup_required.createdb_command}
      />
    );
  }

  const homeHref = serverState.linkGenerator.homeController({});

  return (
    <>
      <Background />
      <div className="fg-wrap">
        <Masthead homeHref={homeHref} />

        <main className="fg-hero-main">
          <div className="fg-eyebrow fg-rise" style={{ animationDelay: "0.05s" }}>
            <span className="fg-dot" />
            <span>Task{serverState.id != null ? ` #${serverState.id}` : ""}</span>
          </div>

          <h1 className="fg-display fg-rise" style={{ animationDelay: "0.1s", fontSize: "clamp(40px, 6vw, 72px)" }}>
            Task <span className="fg-pine">details</span>
          </h1>

          <div className="fg-rise" style={{ animationDelay: "0.2s", marginTop: "26px" }}>
            <a className="fg-back" href={homeHref}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
              Back to the route
            </a>
          </div>
        </main>

        <section className="fg-panel fg-rise" style={{ animationDelay: "0.28s", marginBottom: "40px" }}>
          <div style={{ marginBottom: "28px" }}>
            <span className="fg-tag">Current description</span>
            <p className="fg-current">{serverState.description}</p>
          </div>

          <div className="fg-rule" style={{ marginBottom: "24px" }} />

          <span className="fg-tag">Update description</span>
          <div className="fg-input-row">
            <input
              className="fg-input"
              type="text"
              value={text}
              placeholder="Write a new description…"
              onChange={(e) => setText(e.target.value)}
            />
            <button
              className="fg-btn fg-primary"
              type="button"
              disabled={!text.trim()}
              onClick={async () => {
                await serverState.update_text({
                  detail_id: serverState.id!,
                  requestBody: { description: text },
                });
                setText("");
              }}
            >
              Save
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </button>
          </div>
        </section>

        <div className="fg-rule" />
        <footer className="fg-foot">
          <span className="fg-foot-l">
            Edit <code>views/app/detail/page.tsx</code>
          </span>
          <span className="fg-foot-r">37.9235° N · 122.5965° W</span>
        </footer>
      </div>
    </>
  );
};

export default Page;
{% endraw %}
{% endif %}
