import { lazy, Suspense } from "react";
import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider, QueryCache, MutationCache } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "next-themes";
import NotFound from "@/pages/not-found";
import { Layout } from "@/components/layout";
import { Spinner } from "@/components/ui/spinner";

const Home = lazy(() => import("@/pages/home"));
const GeneratePaper = lazy(() => import("@/pages/generate"));
const QuestionBank = lazy(() => import("@/pages/questions"));
const History = lazy(() => import("@/pages/history"));
const Settings = lazy(() => import("@/pages/settings"));
const Login = lazy(() => import("@/pages/login"));
const Review = lazy(() => import("@/pages/review"));
const UploadCenter = lazy(() => import("@/pages/upload"));
const Subjects = lazy(() => import("@/pages/subjects"));
const KnowledgeBase = lazy(() => import("@/pages/knowledge"));
const Analytics = lazy(() => import("@/pages/analytics"));

import { setAuthTokenGetter } from "@workspace/api-client-react";

// Initialize auth token getter
setAuthTokenGetter(() => localStorage.getItem("access_token"));

const handleError = (error: any) => {
  if (error?.status === 401 || error?.response?.status === 401) {
    toast.error("Session expired or unauthorized. Please login again.");
    localStorage.removeItem("access_token");
    window.location.href = "/login";
  } else {
    toast.error(`Error: ${error.message || "An unexpected error occurred"}`);
  }
};

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: handleError,
  }),
  mutationCache: new MutationCache({
    onError: handleError,
  }),
});

function Router() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center">
          <Spinner />
        </div>
      }
    >
      <Switch>
        <Route path="/login" component={Login} />
        <Route path="/" component={Home} />
        <Route path="/subjects" component={Subjects} />
        <Route path="/upload" component={UploadCenter} />
        <Route path="/knowledge" component={KnowledgeBase} />
        <Route path="/generate" component={GeneratePaper} />
        <Route path="/questions" component={QuestionBank} />
        <Route path="/history" component={History} />
        <Route path="/review" component={Review} />
        <Route path="/analytics" component={Analytics} />
        <Route path="/settings" component={Settings} />
        <Route component={NotFound} />
      </Switch>
    </Suspense>
  );
}

function App() {
  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <WouterRouter base={import.meta.env.BASE_URL?.replace(/\/$/, "") || ""}>
            <Layout>
              <Router />
            </Layout>
          </WouterRouter>
          <Toaster richColors position="top-right" />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
