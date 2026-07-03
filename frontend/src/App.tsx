import { useState } from "react";
import { HashRouter } from "react-router-dom";
import { AppRouter } from "./router";
import { AuthScreen } from "./components/AuthScreen";
import { hasApiKey } from "./lib/auth";

export default function App() {
  // Gate the app on a stored API key (queried from main). Until one is set, show
  // the auth screen; the whole app talks to the API only through the bridge.
  const [authed, setAuthed] = useState(() => hasApiKey());

  if (!authed) return <AuthScreen onAuthenticated={() => setAuthed(true)} />;

  return (
    <HashRouter>
      <AppRouter />
    </HashRouter>
  );
}
