import { useState } from "react";
import Card from "../components/ui/Card.jsx";
import Button from "../components/ui/Button.jsx";
import Input from "../components/ui/Input.jsx";

const SECTIONS = ["Profile", "Organization", "Security", "Notifications", "Billing"];

export default function SettingsPage() {
  const [section, setSection] = useState("Profile");
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  async function onSave() {
    setSaving(true);
    await new Promise((resolve) => setTimeout(resolve, 600));
    setSaving(false);
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 16 }}>
      <Card title="Settings">
        <div style={{ display: "grid", gap: 6 }}>
          {SECTIONS.map((x) => (
            <Button key={x} variant={section === x ? "primary" : "ghost"} size="sm" onClick={() => setSection(x)}>
              {x}
            </Button>
          ))}
        </div>
      </Card>

      <Card title={`${section} settings`} subtitle="Changes auto-save ready">
        <div style={{ display: "grid", gap: 12, maxWidth: 520 }}>
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} helperText="Displayed across workspace" />
          <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} helperText="Used for notifications" />
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="primary" loading={saving} onClick={onSave}>Save changes</Button>
            <Button variant="secondary">Cancel</Button>
          </div>
        </div>
        <div style={{ marginTop: 24, paddingTop: 16, borderTop: "1px solid var(--cc-border)" }}>
          <h3 style={{ marginTop: 0, color: "var(--cc-danger)" }}>Danger zone</h3>
          <Button
            variant="danger"
            onClick={() => {
              if (window.confirm("Delete account permanently? This action cannot be undone.")) {
                // Placeholder action: wire API in next backend pass.
              }
            }}
          >
            Delete account
          </Button>
        </div>
      </Card>
    </div>
  );
}
