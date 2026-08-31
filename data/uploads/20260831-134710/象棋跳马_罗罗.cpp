#include<bits/stdc++.h>
using namespace std;
int ans = 0;
int used[1000][1000];
int fx[4][2] = {{1,-2},{2,-1},{2,1},{1,2}};
int n,m,x,y,q,p;
void dfs(int x,int y){
	if(x == q && y == p){
		ans++;
		return;
	} else {
		used[x][y] = 1;
		for(int i = 0;i < 4;i++){
			int nx = x + fx[i][0];
			int ny = y + fx[i][1];
			if(nx >= 0 && nx <= m && ny >= 0 && ny <= n && used[nx][ny] == 0){
				used[nx][ny] = 1;
				dfs(nx,ny);
				used[nx][ny] = 0;
			}
		}
		used[x][y] = 0;
	}
}
int main()
{
	cin>>m>>n;
	cin>>x>>y;
	cin>>q>>p;
	dfs(x,y);
	cout << ans;
}
