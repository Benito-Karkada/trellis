import { useEffect, useState } from "react";
import { Copy, ExternalLink, KeyRound, Trash2, X } from "lucide-react";
import { api } from "./api";
type Token = {
  id: string;
  name: string;
  owner: string;
  scopes: string[];
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};
type Access = {
  course_id: number;
  tokens: Token[];
  scopes: Record<string, string>;
  default_scopes: string[];
};
export default function ApiAccess() {
  const [data, setData] = useState<Access | null>(null),
    [name, setName] = useState(""),
    [days, setDays] = useState(30),
    [scopes, setScopes] = useState<string[]>([]),
    [secret, setSecret] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  async function load(initial = false) {
    const d = await api("settings/api-tokens/");
    setData(d);
    if (initial) setScopes(d.default_scopes);
  }
  useEffect(() => {
    load(true).catch((e) => setError(e.message));
  }, []);
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    setSecret("");
    try {
      const d = await api("settings/api-tokens/", {
        name,
        scopes,
        expires_in_days: days,
      });
      setSecret(d.token);
      setName("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function revoke(token: Token) {
    if (
      !window.confirm(
        `Revoke “${token.name}”? Scripts using it will lose access immediately.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await api(`settings/api-tokens/${token.id}/revoke/`, {});
      setNotice("Token revoked.");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!data) return <p role="status">{error || "Loading API access…"}</p>;
  return (
    <div className="api-access">
      <section className="settings-card">
        <div className="card-title">
          <div>
            <h2>Developer API</h2>
            <p>
              Read course data and make versioned content changes from your
              scripts. Course ID: <strong>{data.course_id}</strong>.
            </p>
          </div>
          <KeyRound />
        </div>
        <a
          className="api-doc-link"
          href="/api/v1/docs/"
          target="_blank"
          rel="noopener noreferrer"
        >
          Open API documentation <ExternalLink size={16} />
        </a>
        <p>
          Tokens have the permissions selected below and work only for this
          course. Content read access includes staff files, graders, and answer
          keys.
        </p>
      </section>
      {error && (
        <div className="notification error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="notification" role="status">
          {notice}
        </div>
      )}
      {secret && (
        <section className="login-created" role="status">
          <div>
            <KeyRound />
            <strong>Copy your token</strong>
            <button
              aria-label="Dismiss API token"
              onClick={() => setSecret("")}
            >
              <X size={18} />
            </button>
          </div>
          <p>
            This token is shown only now. Keep it in an environment variable or
            secret store; don’t commit it to Git.
          </p>
          <code className="api-secret">{secret}</code>
          <button
            onClick={() =>
              navigator.clipboard
                .writeText(secret)
                .then(() => setNotice("Token copied."))
                .catch(() =>
                  setError("Could not copy. Select the token text to copy it."),
                )
            }
          >
            <Copy size={16} />
            Copy token
          </button>
        </section>
      )}
      <section className="settings-card">
        <h2>Create an access token</h2>
        <form onSubmit={create}>
          <div className="form-row">
            <label>
              Name
              <input
                required
                maxLength={120}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Grader import script"
              />
            </label>
            <label>
              Expires in days
              <input
                type="number"
                required
                min={1}
                max={365}
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="api-scopes">
            {Object.entries(data.scopes).map(([scope, description]) => (
              <label key={scope}>
                <input
                  type="checkbox"
                  checked={scopes.includes(scope)}
                  onChange={(e) =>
                    setScopes((old) =>
                      e.target.checked
                        ? [...old, scope]
                        : old.filter((s) => s !== scope),
                    )
                  }
                />
                <span>
                  <strong>{scope}</strong>
                  <small>{description}</small>
                </span>
              </label>
            ))}
          </div>
          <button className="primary" disabled={busy || !scopes.length}>
            Create token
          </button>
        </form>
      </section>
      <section className="settings-card">
        <h2>Access tokens</h2>
        <div className="api-token-list">
          {data.tokens.map((t) => (
            <div key={t.id}>
              <div>
                <strong>{t.name}</strong>
                <small>
                  {t.owner} ·{" "}
                  {t.revoked_at
                    ? "Revoked"
                    : new Date(t.expires_at) <= new Date()
                      ? "Expired"
                      : `Expires ${new Date(t.expires_at).toLocaleDateString()}`}
                </small>
                <p>{t.scopes.join(" · ")}</p>
                <small>
                  Last used:{" "}
                  {t.last_used_at
                    ? new Date(t.last_used_at).toLocaleString()
                    : "Never"}
                </small>
              </div>
              <button
                disabled={busy || !!t.revoked_at}
                onClick={() => revoke(t)}
              >
                <Trash2 size={15} />
                Revoke
              </button>
            </div>
          ))}
          {!data.tokens.length && <p>No API tokens created yet.</p>}
        </div>
      </section>
    </div>
  );
}
