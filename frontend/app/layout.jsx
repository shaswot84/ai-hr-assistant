import "./globals.css";

export const metadata = {
  title: "AI HR Assistant",
  description: "Knowledge ingestion and retrieval UI",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <span className="brand">AI HR Assistant</span>
          <nav className="nav">
            <a href="/ingest">Ingestion</a>
            <a href="/search">Knowledge Search</a>
          </nav>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
