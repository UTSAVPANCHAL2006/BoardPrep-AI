import type { Metadata } from "next";
import { Inter, Plus_Jakarta_Sans } from "next/font/google";
import { Navbar } from "@/components/Navbar";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-jakarta" });

export const metadata: Metadata = {
  title: "BoardPrep AI | UPSC Mock Interview",
  description:
    "Voice-first UPSC personality test prototype — DAF-aware mock interview, daily current affairs, and Hindi voice briefings.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${jakarta.variable} font-sans`}>
        <div className="ambient-bg" />
        <div className="relative z-10 min-h-screen bg-mesh">
          <Navbar />
          <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
