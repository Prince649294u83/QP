import re

file_path = r'e:\Projects\QP\frontend\qp-maker\src\pages\generate.tsx'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()


# 1. Update moduleCoMapping checkbox to only allow one CO
old_checkbox = '''                                  <div className="flex flex-wrap gap-2">
                                    {["CO1", "CO2", "CO3", "CO4", "CO5"].map(co => (
                                      <label key={co} className="flex items-center gap-1.5 text-xs">
                                        <Checkbox
                                          className="h-3.5 w-3.5"
                                          checked={(moduleCoMapping[moduleNumber] || []).includes(co)}
                                          onCheckedChange={(checked) => {
                                            setModuleCoMapping(prev => {
                                              const currentCOs = prev[moduleNumber] || [];
                                              const newCOs = checked
                                                ? [...currentCOs, co].sort()
                                                : currentCOs.filter(c => c !== co);
                                              return { ...prev, [moduleNumber]: newCOs };
                                            });
                                          }}
                                        />
                                        <span>{co}</span>
                                      </label>
                                    ))}
                                  </div>'''
new_checkbox = '''                                  <div className="flex flex-wrap gap-2">
                                    {["CO1", "CO2", "CO3", "CO4", "CO5"].map(co => (
                                      <label key={co} className="flex items-center gap-1.5 text-xs">
                                        <Checkbox
                                          className="h-3.5 w-3.5"
                                          checked={(moduleCoMapping[moduleNumber] || []).includes(co)}
                                          onCheckedChange={(checked) => {
                                            setModuleCoMapping(prev => ({
                                              ...prev,
                                              [moduleNumber]: checked ? [co] : []
                                            }));
                                          }}
                                        />
                                        <span>{co}</span>
                                      </label>
                                    ))}
                                  </div>'''
content = content.replace(old_checkbox, new_checkbox)
content = content.replace('Map to Course Outcomes:', 'Map to Course Outcome (Select ONE):')

# 2. Disable sliders for difficultyDist
# Easy
old_slider_easy = '''                            <Slider
                              value={[difficultyDist.easy]}
                              max={100}
                              step={5}
                              onValueChange={(val) => setDifficultyDist(prev => ({ ...prev, easy: val[0] }))}
                            />'''
new_slider_easy = '''                            <Slider
                              value={[difficultyDist.easy]}
                              max={100}
                              step={5}
                              disabled
                            />'''
content = content.replace(old_slider_easy, new_slider_easy)

# Medium
old_slider_medium = '''                            <Slider
                              value={[difficultyDist.medium]}
                              max={100}
                              step={5}
                              onValueChange={(val) => setDifficultyDist(prev => ({ ...prev, medium: val[0] }))}
                            />'''
new_slider_medium = '''                            <Slider
                              value={[difficultyDist.medium]}
                              max={100}
                              step={5}
                              disabled
                            />'''
content = content.replace(old_slider_medium, new_slider_medium)

# Hard
old_slider_hard = '''                            <Slider
                              value={[difficultyDist.hard]}
                              max={100}
                              step={5}
                              onValueChange={(val) => setDifficultyDist(prev => ({ ...prev, hard: val[0] }))}
                            />'''
new_slider_hard = '''                            <Slider
                              value={[difficultyDist.hard]}
                              max={100}
                              step={5}
                              disabled
                            />'''
content = content.replace(old_slider_hard, new_slider_hard)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Replaced slider and checkbox logic')
