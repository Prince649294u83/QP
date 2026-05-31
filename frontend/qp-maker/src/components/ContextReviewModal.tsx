import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { authFetchBlob, useDocumentPreview } from "@/lib/academic-api";
import { AlertTriangle, Loader2, FileText, Image as ImageIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function ContextReviewModal({ documentId, open, onOpenChange }: { documentId: number | null, open: boolean, onOpenChange: (open: boolean) => void }) {
  const { data: preview, isError, isLoading } = useDocumentPreview(documentId || 0);

  return (
    <Dialog open={open && documentId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl h-[85vh] flex flex-col p-6">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl font-semibold">
            <FileText className="h-5 w-5 text-primary" />
            Context Review
            {preview && <span className="text-sm font-normal text-muted-foreground ml-2">({preview.filename})</span>}
          </DialogTitle>
          <DialogDescription>
            Review extracted text chunks and available image previews before using this document for generation.
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
            <Loader2 className="h-8 w-8 animate-spin mb-4" />
            <p>Loading document context...</p>
          </div>
        ) : preview ? (
          <Tabs defaultValue="text" className="flex-1 flex flex-col hidden-scrollbar mt-4">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="text" className="flex items-center gap-2">
                <FileText className="h-4 w-4" />
                Text Chunks ({preview.chunks.length})
              </TabsTrigger>
              <TabsTrigger value="images" className="flex items-center gap-2">
                <ImageIcon className="h-4 w-4" />
                Extracted Images ({preview.images.length})
              </TabsTrigger>
            </TabsList>

            <TabsContent value="text" className="flex-1 min-h-0 mt-4 outline-none data-[state=active]:flex flex-col">
              <ScrollArea className="h-full pr-4">
                <div className="space-y-4">
                  {preview.chunks.length === 0 ? (
                    <div className="text-center text-muted-foreground py-12">No text chunks extracted.</div>
                  ) : (
                    preview.chunks.map((chunk) => (
                      <div key={chunk.id} className="p-4 rounded-xl border border-border/40 bg-card hover:border-primary/30 transition-colors">
                        <div className="flex items-center justify-between mb-2">
                          <Badge variant="secondary" className="text-[10px] uppercase font-medium">Page {chunk.page}</Badge>
                          <span className="text-xs text-muted-foreground">{chunk.source_type}</span>
                        </div>
                        <p className="text-sm text-foreground/90 whitespace-pre-wrap font-mono leading-relaxed">{chunk.text}</p>
                      </div>
                    ))
                  )}
                </div>
              </ScrollArea>
            </TabsContent>

            <TabsContent value="images" className="flex-1 min-h-0 mt-4 outline-none data-[state=active]:flex flex-col">
              <ScrollArea className="h-full pr-4">
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  {preview.images.length === 0 ? (
                    <div className="col-span-full text-center text-muted-foreground py-12">No images extracted.</div>
                  ) : (
                    preview.images.map((img) => (
                      <div key={img.id} className="overflow-hidden rounded-xl border border-border bg-muted/20">
                        <AuthenticatedPreviewImage
                          imageId={img.id}
                          alt={img.ai_caption || "Extracted image"}
                          available={img.image_available !== false}
                        />
                        <div className="space-y-2 p-3">
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-xs font-medium text-foreground">{img.ai_caption || "No caption"}</p>
                            <Badge variant="secondary" className="shrink-0 text-[9px]">Page {img.source_page}</Badge>
                          </div>
                          {img.keywords.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              {img.keywords.slice(0, 5).map((kw, i) => (
                                <Badge key={i} variant="outline" className="h-4 px-1 py-0 text-[9px]">{kw}</Badge>
                              ))}
                            </div>
                          )}
                          {(img.context_before || img.context_after) && (
                            <p className="line-clamp-3 text-[11px] leading-relaxed text-muted-foreground">
                              {img.context_before || img.context_after}
                            </p>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </ScrollArea>
            </TabsContent>
          </Tabs>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
            <AlertTriangle className="h-8 w-8 mb-4 text-destructive" />
            <p>{isError ? "Failed to load preview" : "No preview available"}</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function AuthenticatedPreviewImage({ imageId, alt, available }: { imageId: number; alt: string; available: boolean }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!available) {
      setFailed(true);
      setSrc(null);
      return;
    }

    let objectUrl: string | null = null;
    let cancelled = false;

    authFetchBlob(`/academic/documents/images/${imageId}`)
      .then((blob) => {
        if (cancelled) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [available, imageId]);

  if (failed) {
    return (
      <div className="flex h-40 items-center justify-center bg-muted text-xs text-muted-foreground">
        Image preview unavailable
      </div>
    );
  }

  if (!src) {
    return (
      <div className="flex h-40 items-center justify-center bg-muted text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className="h-40 w-full object-contain bg-white"
    />
  );
}
