import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "adala ai",
  description: "Grounded AI research over uploaded Egyptian legal documents.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
