#!/usr/bin/env python3
"""Optional native systemd load test; only a uniquely named fixture unit is touched.

Requires the same AIPROXY_TEST_* binaries as test_dns_doh.py and root in a test VM.
"""
import importlib.util,os,json,socket,struct,subprocess,time,uuid,shutil,tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
p=Path(__file__).with_name('test_dns_doh.py');spec=importlib.util.spec_from_file_location('native',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
tempfile.tempdir="/run";c=m.NativeDohTests;c.setUpClass();name='aiproxy-doh-budget-'+uuid.uuid4().hex[:10]
try:
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 binary=c.root/'dnsproxy';shutil.copy2(os.environ['AIPROXY_TEST_DNSPROXY'],binary);binary.chmod(0o755)
 conf=c.root/'budget.yml';conf.write_text(c.config.replace('listen-ports: ['+str(c.bridge)+']','listen-ports: ['+str(port)+']'))
 args=['systemd-run','--quiet','--unit='+name,'-p','DynamicUser=yes','-p','MemoryMax=32M','-p','MemorySwapMax=0','-p','PrivateTmp=yes','-p','ProtectSystem=strict','-p','ProtectHome=yes','-p','NoNewPrivileges=yes','--setenv=GOMEMLIMIT=16MiB','--setenv=GOGC=50','--setenv=GOMAXPROCS=1',str(binary),'--config-path='+str(conf)]
 subprocess.run(args,check=True,capture_output=True)
 for _ in range(100):
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=.1):break
  except OSError:time.sleep(.03)
 def query(i):
  label=('q'+str(i)).encode();q=struct.pack('!6H',i%65536,0x100,1,0,0,0)+bytes([len(label)])+label+b'\x07example\x03com\0\0\1\0\1'
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
   client.settimeout(6);client.sendto(q,('127.0.0.1',port));r=client.recv(4096);assert r[:2]==q[:2]
 with ThreadPoolExecutor(max_workers=32) as pool:list(pool.map(query,range(2000)))
 values=subprocess.check_output(['systemctl','show',name,'-p','MemoryCurrent','-p','MemoryPeak','-p','NRestarts','-p','ActiveState','-p','MemoryMax'],text=True)
 stats=dict(line.split('=',1) for line in values.splitlines());assert stats['ActiveState']=='active' and stats['NRestarts']=='0';assert int(stats['MemoryPeak']) <= 32*1048576
 print(json.dumps({'queries':2000,'concurrency':32,'unit':dict(line.split('=',1) for line in values.splitlines())}))
finally:
 subprocess.run(['systemctl','stop',name],capture_output=True);subprocess.run(['systemctl','reset-failed',name],capture_output=True);c.cleanup()