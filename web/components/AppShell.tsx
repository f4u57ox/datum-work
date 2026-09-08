"use client";

import { usePathname } from "next/navigation";
import { GlobalMenuProvider } from "@/components/GlobalMenuContext";
import { DataStreamProvider } from "@/lib/DataStreamContext";
import { BlocksProvider } from "@/lib/BlocksContext";
import { VisualizationProvider } from "@/components/VisualizationContext";
import { TimingDisplayProvider } from "@/components/TimingDisplayContext";
import { HistoricalDataProvider } from "@/lib/HistoricalDataContext";
import { SelectedTemplateProvider } from "@/lib/SelectedTemplateContext";
import { PoolFilterProvider } from "@/components/PoolFilterContext";
import ClientNavigation from "@/components/ClientNavigation";


export default function AppShell({children}: {children: React.ReactNode}) {
  const pathname = usePathname();
  if (pathname === "/") return <>{children}</>;
  return (
          <DataStreamProvider>
            <PoolFilterProvider>
            <BlocksProvider>
              <HistoricalDataProvider>
                <SelectedTemplateProvider>
                  <GlobalMenuProvider>
                    <VisualizationProvider>
                    <TimingDisplayProvider>
                      {/* ClientNavigation handles passing the blockHeight to Navigation */}
                      <ClientNavigation>
                        {children}
                      </ClientNavigation>
                    </TimingDisplayProvider>
                    </VisualizationProvider>
                  </GlobalMenuProvider>
                </SelectedTemplateProvider>
              </HistoricalDataProvider>
            </BlocksProvider>
            </PoolFilterProvider>
          </DataStreamProvider>
  );
}
