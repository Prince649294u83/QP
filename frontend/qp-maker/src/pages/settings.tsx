import { Building2, Save, BookOpen, Settings2, LayoutTemplate, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { toast } from "sonner";

export default function Settings() {
  const handleSave = () => {
    toast.success("Settings saved successfully");
  };

  return (
    <div className="space-y-6 max-w-4xl pb-10">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-foreground font-serif tracking-tight">Settings</h1>
          <p className="text-muted-foreground">Configure institutional preferences and AI defaults.</p>
        </div>
        <Button onClick={handleSave} className="hover-elevate">
          <Save className="mr-2 h-4 w-4" /> Save Changes
        </Button>
      </div>

      <div className="grid gap-6">
        <Card className="border-muted shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Building2 className="h-5 w-5 text-primary" /> Institution Details
            </CardTitle>
            <CardDescription>Header information used in question paper templates.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Institution Name</Label>
              <Input defaultValue="Dayananda Sagar Academy of Technology & Management" />
            </div>
            <div className="space-y-2">
              <Label>Affiliation & Accreditations</Label>
              <Input defaultValue="(Autonomous Institute under VTU) Affiliated to VTU | Approved by AICTE | Accredited by NAAC with A+ Grade" />
            </div>
          </CardContent>
        </Card>

        <Card className="border-muted shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <LayoutTemplate className="h-5 w-5 text-primary" /> Institutional Template Builder
            </CardTitle>
            <CardDescription>Upload custom logos and design your question paper formatting.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Left Logo</Label>
                <div className="border-2 border-dashed rounded-lg p-6 flex flex-col items-center justify-center text-muted-foreground hover:bg-muted/50 cursor-pointer transition-colors">
                  <Upload className="h-6 w-6 mb-2" />
                  <span className="text-sm">Click to upload (PNG/JPG)</span>
                </div>
              </div>
              <div className="space-y-2">
                <Label>Right Logo</Label>
                <div className="border-2 border-dashed rounded-lg p-6 flex flex-col items-center justify-center text-muted-foreground hover:bg-muted/50 cursor-pointer transition-colors">
                  <Upload className="h-6 w-6 mb-2" />
                  <span className="text-sm">Click to upload (PNG/JPG)</span>
                </div>
              </div>
            </div>
            <Separator />
            <div className="space-y-4">
              <Label className="text-base">Canvas Builder</Label>
              <p className="text-sm text-muted-foreground">Build the question paper header from scratch or upload your existing pattern.</p>
              <Button variant="outline" className="w-full" onClick={() => toast.info("Canvas Builder opening... (Preview)")}>
                <LayoutTemplate className="mr-2 h-4 w-4" /> Open Interactive Template Builder
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="border-muted shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Settings2 className="h-5 w-5 text-primary" /> AI Generation Defaults
            </CardTitle>
            <CardDescription>Configure the default behavior of the AI paper generator.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-8">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label className="text-base">Prefer Higher Order Thinking (L4-L6)</Label>
                <p className="text-sm text-muted-foreground">AI will attempt to select questions with higher Bloom's levels when possible.</p>
              </div>
              <Switch defaultChecked />
            </div>
            
            <Separator />
            
            <div className="space-y-4">
              <Label className="text-base">Default Difficulty Target</Label>
              <div className="space-y-6 bg-muted/20 p-6 rounded-lg border">
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <Label className="text-sm font-medium">Easy (L1, L2)</Label>
                    <span className="text-sm text-muted-foreground">30%</span>
                  </div>
                  <Slider defaultValue={[30]} max={100} step={5} />
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <Label className="text-sm font-medium">Medium (L3, L4)</Label>
                    <span className="text-sm text-muted-foreground">50%</span>
                  </div>
                  <Slider defaultValue={[50]} max={100} step={5} />
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <Label className="text-sm font-medium">Hard (L5, L6)</Label>
                    <span className="text-sm text-muted-foreground">20%</span>
                  </div>
                  <Slider defaultValue={[20]} max={100} step={5} />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-muted shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <BookOpen className="h-5 w-5 text-primary" /> Template Preferences
            </CardTitle>
            <CardDescription>Customize what appears on the generated paper.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Show College Logo Header</Label>
                <p className="text-sm text-muted-foreground">Include the placeholder for institutional logos at the top.</p>
              </div>
              <Switch defaultChecked />
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Include RBT & CO Legend</Label>
                <p className="text-sm text-muted-foreground">Print the Bloom's taxonomy definitions before questions.</p>
              </div>
              <Switch defaultChecked />
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Include Course Outcomes Table</Label>
                <p className="text-sm text-muted-foreground">Append the CO mapping definitions at the end of the paper.</p>
              </div>
              <Switch defaultChecked />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
