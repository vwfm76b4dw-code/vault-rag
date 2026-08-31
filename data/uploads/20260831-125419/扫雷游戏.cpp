#include <bits/stdc++.h>
using namespace std;
int dx[8]={1,0,0,-1,1,1,-1,-1};
int dy[8]={0,1,-1,0,-1,1,-1,1};
char a[500][500];
int n,m;
int main()
{
	cin>>n>>m;
	for(int i=1;i<=n;i++)
		for(int j=1;j<=m;j++)cin>>a[i][j];
	for(int i=1;i<=n;i++){
		for(int j=1;j<=m;j++){
			if(a[i][j]=='?'){
				int cnt=0;
				for(int x=0;x<8;x++){
					if(a[i+dx[x]][j+dy[x]]=='*'){
						cnt++;
					}
				}
				cout<<cnt;
			}else{
				cout<<'*';
			}
		}
		cout<<endl;
	}
}
