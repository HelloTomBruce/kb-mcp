import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HeroUIProvider } from '@heroui/react';
import { Toaster } from 'sonner';
import { Layout } from './components/Layout';
import { OverviewPage } from './pages/Overview';
import { DocumentsPage } from './pages/Documents';
import { DocDetailPage } from './pages/DocDetail';
import { TypesPage } from './pages/Types';
import { SearchPage } from './pages/Search';
import { LinksPage } from './pages/Links';
import { GraphViewPage } from './pages/GraphView';
import { ImportsPage } from './pages/Imports';
import { GitPage } from './pages/Git';
import { SchedulerPage } from './pages/Scheduler';
import { HealthPage } from './pages/Health';
import { SettingsPage } from './pages/Settings';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 1000 * 10,
    },
  },
});

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <HeroUIProvider>
        <Toaster position="top-right" richColors closeButton />
        <BrowserRouter basename="/app">
          <Routes>
            <Route path="/" element={<Layout />}>
              <Route index element={<OverviewPage />} />
              <Route path="docs" element={<DocumentsPage />} />
              <Route path="docs/:docId" element={<DocDetailPage />} />
              <Route path="types" element={<TypesPage />} />
              <Route path="search" element={<SearchPage />} />
              <Route path="links" element={<LinksPage />} />
              <Route path="graph" element={<GraphViewPage />} />
              <Route path="imports" element={<ImportsPage />} />
              <Route path="git" element={<GitPage />} />
              <Route path="scheduler" element={<SchedulerPage />} />
              <Route path="health" element={<HealthPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </HeroUIProvider>
    </QueryClientProvider>
  );
};
