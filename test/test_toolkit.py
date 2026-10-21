import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.work=Path(self.temp.name);self.dist=self.work/'dist'
        self.generate()
    def tearDown(self):self.temp.cleanup()
    def generate(self,manifest=None,out=None):
        return subprocess.run(['node',str(ROOT/'scene-page-generator.mjs'),'--shell',str(ROOT/'examples/shell.html'),'--pages',str(manifest or ROOT/'examples/pages.json'),'--out',str(out or self.dist),'--site-url','https://example.test'],capture_output=True,text=True,check=manifest is None)
    def check_site(self):
        r=subprocess.run(['python3',str(ROOT/'publish_check.py'),'--local','--dir',str(self.dist),'--site-url','https://example.test','--reference-url','https://reference.example','--reference-file',str(ROOT/'examples/reference.html'),'--require-text','Review before publishing','--forbid-text','unverified claim','--output',str(self.work/'report')],capture_output=True,text=True)
        return r,json.loads((self.work/'report/report.json').read_text())
    def test_generated_nested_pages_and_all_six_green(self):
        self.assertTrue((self.dist/'guides/portrait.html').is_file())
        r,data=self.check_site();self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(data['ok']);self.assertEqual(len(data['sections']),6)
        self.assertEqual(data['overlap']['n'],8);self.assertEqual(data['overlap']['matched_owned_positions'],0)
    def test_broken_link_fails_stage_three(self):
        p=self.dist/'index.html';p.write_text(p.read_text().replace('</main>','<a href="/nope">Broken target</a></main>'))
        r,data=self.check_site();self.assertEqual(r.returncode,1);self.assertEqual(data['sections'][-1]['number'],3);self.assertIn('nope',data['sections'][-1]['error']);self.assertEqual(len(data['sections']),3)
    def test_forbidden_fact_inside_schema_fails_stage_four(self):
        p=self.dist/'index.html';p.write_text(p.read_text().replace('"@context":','"policy":"unverified claim","@context":'))
        r,data=self.check_site();self.assertEqual(r.returncode,1);self.assertEqual(data['sections'][-1]['number'],4)
    def test_missing_organization_fails_stage_two(self):
        p=self.dist/'index.html';p.write_text(p.read_text().replace('"@type":"Organization"','"@type":"Thing"'))
        r,data=self.check_site();self.assertEqual(r.returncode,1);self.assertEqual(data['sections'][-1]['number'],2)
    def test_duplicate_paths_rejected_before_writes(self):
        values=json.loads((ROOT/'examples/pages.json').read_text());values.append(values[0]);m=self.work/'duplicate.json';m.write_text(json.dumps(values));output=self.work/'duplicate-dist';r=self.generate(m,output)
        self.assertNotEqual(r.returncode,0);self.assertIn('Duplicate',r.stderr);self.assertFalse(output.exists())
    def test_traversal_rejected_before_writes(self):
        values=json.loads((ROOT/'examples/pages.json').read_text());values[0]['path']='/../escape';m=self.work/'unsafe.json';m.write_text(json.dumps(values));output=self.work/'unsafe-dist';r=self.generate(m,output)
        self.assertNotEqual(r.returncode,0);self.assertIn('Unsafe path',r.stderr);self.assertFalse(output.exists())
    def test_text_and_jsonld_escaping(self):
        values=json.loads((ROOT/'examples/pages.json').read_text());values[0]['title']='A </script><img src=x> & B';m=self.work/'escaped.json';m.write_text(json.dumps(values));output=self.work/'escaped-dist';r=self.generate(m,output)
        self.assertEqual(r.returncode,0,r.stderr);s=(output/'index.html').read_text();self.assertIn('A &lt;/script&gt;&lt;img src=x&gt; &amp; B',s);self.assertIn('\\u003c/script\\u003e',s)

if __name__=='__main__':unittest.main()
