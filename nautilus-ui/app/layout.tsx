import "./../styles/globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "NAUTILUS Trading Command Center",
  description: "Multi-strategy, multi-venue trading cockpit",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-bg-primary text-text-primary font-body antialiased">
        {children}
      </body>
    </html>
  );
}
