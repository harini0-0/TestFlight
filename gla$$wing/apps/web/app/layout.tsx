import "./globals.css";
import { Shell } from "@/components/Shell";

export const metadata = { title: "AI procurement control", description: "Compile supplier documents into a live rule engine" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
