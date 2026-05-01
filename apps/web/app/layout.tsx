import "./globals.css";
import { ThemeProvider } from "./theme";

export const metadata = {
  title: "edwinxu-agent",
  description: "Web chat for edwinxu-agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh" suppressHydrationWarning>
      <body>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}

